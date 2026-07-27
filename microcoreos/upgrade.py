"""
`microcoreos upgrade` — the mitigation for honest vendoring.

Tools and domains are copied into the project as the user's source, so a fix
upstream does not reach them. Nothing can change that without taking the files
back, which is the whole point of materializing them. What CAN be done is tell
you exactly what changed and update only the files you never touched.

That distinction needs a baseline: `microcoreos new` records the SHA-256 of
every file it wrote (`.microcoreos/manifest.json`). With it, three states are
distinguishable that are otherwise indistinguishable:

    local == baseline, upstream != baseline   you never touched it → safe to update
    local != baseline, upstream == baseline   your edit, upstream quiet → leave alone
    local != baseline, upstream != baseline   both moved → CONFLICT, show it, touch nothing

Without the manifest only "differs from upstream" is visible, which cannot
tell your work from an old version — and overwriting on that basis destroys
edits. So a project with no manifest is an error, not a degraded mode.

`microcoreos add` moves folders out of extras/, which is why the manifest also
records those moves: the baseline is always keyed by the file's UPSTREAM path,
and the move map says where it lives in this project now. Without it an
upgrade would silently skip the infrastructure you deliberately installed.

Two cases sit outside that table, and both follow the same rule — the
framework may withdraw what you never touched, nothing else:

    absent upstream, local == baseline   its file, withdrawn → deleted
    absent upstream, local != baseline   your file now → released from tracking

And a folder can be moved somewhere no convention predicts (`mv
extras/available_tools/postgresql tools/my-db`). Names cannot follow that, but
content can: an unedited file still hashes to its baseline digest wherever it
sits, so `find_renames` locates it and writes the move down — after which it is
tracked by name like any other, editable without being lost again.
"""

import os
import json
import shutil
import hashlib

MANIFEST_DIR = ".microcoreos"
MANIFEST_NAME = "manifest.json"

# Never part of the project's own source. Rename detection walks the whole
# project, and without this it would walk a virtualenv.
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".idea",
    "dist", "build", MANIFEST_DIR,
}

# A template missing whole entries — a partial wheel, a broken install — is
# indistinguishable from "upstream deleted everything". Deleting on that
# reading would empty the user's project, so past this share of the baseline
# a disappearance is read as a bad template, not as an upgrade.
MAX_REMOVAL_SHARE = 0.25

# Rename detection hashes candidate files, and `_digest` reads a file whole.
# The candidates are the USER's files, which may include a database dump or a
# fixture archive — while the largest thing the framework ships is 39 KB of
# Python. Two orders of magnitude of headroom, and no chance of pulling a
# multi-gigabyte file into memory to compare it against source code.
MAX_RENAME_CANDIDATE_BYTES = 4 * 1024 * 1024


def _digest(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _walk(root: str, entries) -> dict:
    """SHA-256 of every file under the given entries, keyed by relative path."""
    digests = {}
    for entry in entries:
        src = os.path.join(root, entry)
        if os.path.isfile(src):
            digests[entry.replace(os.sep, "/")] = _digest(src)
        elif os.path.isdir(src):
            for dirpath, dirnames, filenames in os.walk(src):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for name in filenames:
                    if name.endswith(".pyc"):
                        continue
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, root).replace(os.sep, "/")
                    digests[rel] = _digest(full)
    return digests


def version() -> str:
    try:
        from importlib.metadata import version as _v
        return _v("microcoreos")
    except Exception:
        return "unknown"


def write_manifest(target: str, entries) -> None:
    """Record what was written, so a later upgrade can tell edits from staleness."""
    path = os.path.join(target, MANIFEST_DIR)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(
            {"version": version(), "files": _walk(target, entries)},
            f, indent=2, sort_keys=True,
        )


def read_manifest(root: str) -> dict | None:
    path = os.path.join(root, MANIFEST_DIR, MANIFEST_NAME)
    if not os.path.isfile(path):
        return None
    try:
        return json.load(open(path, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _conventional_destinations(rel: str) -> list[str]:
    """
    Where an extra ends up when installed BY HAND.

    `microcoreos add` records what it moved, but moving the folder yourself is
    the documented alternative and leaves no record. The framework describes
    exactly three destinations, so this is convention, not guesswork — and each
    is only used if the file is really there.
    """
    parts = rel.split("/")
    if len(parts) < 4 or parts[0] != "extras":
        return []

    kind, name, rest = parts[1], parts[2], "/".join(parts[3:])
    if kind == "available_tools":
        # A transport is not a tool: its driver drops into the event bus.
        if rest == f"{name}_driver.py":
            return [f"tools/event_bus/{rest}", f"tools/{name}/{rest}"]
        return [f"tools/{name}/{rest}"]
    if kind == "available_domains":
        return [f"domains/{name}/{rest}"]
    return []


def resolve(rel: str, moved: dict, root: str | None = None) -> str:
    """
    Where an upstream path lives in THIS project.

    Recorded moves win; failing that, the conventional destination is used when
    a file is actually sitting there. Without this fallback a hand-installed
    extra reports "everything is current" while upstream fixes never arrive —
    silently, which is the worst way to be wrong.
    """
    for src, dst in moved.items():
        if rel == src or rel.startswith(src + "/"):
            return dst + rel[len(src):]

    if root is not None and not os.path.isfile(os.path.join(root, rel)):
        for candidate in _conventional_destinations(rel):
            if os.path.isfile(os.path.join(root, candidate)):
                return candidate

    return rel


def record_moves(root: str, mapping: dict) -> bool:
    """
    Tell the baseline where files went. Nothing under tools/ is touched.

    Returns whether it was written: a report-only `upgrade` records the moves
    it discovers, and a project whose directory is not writable must degrade to
    a correct report rather than a traceback.
    """
    if not mapping:
        return False
    manifest = read_manifest(root)
    if manifest is None:
        return False
    manifest.setdefault("moved", {}).update(mapping)
    try:
        with open(os.path.join(root, MANIFEST_DIR, MANIFEST_NAME), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
    except OSError:
        return False
    return True


def record_move(root: str, src_rel: str, dst_rel: str) -> None:
    """Tell the baseline that an extra was moved out of extras/."""
    record_moves(root, {src_rel: dst_rel})


def _project_files(root: str):
    """Relative paths of every file that could be materialized source."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            full = os.path.join(dirpath, name)
            yield os.path.relpath(full, root).replace(os.sep, "/")


def find_renames(root: str, baseline: dict, moved: dict) -> dict:
    """
    Where a file went when it was moved somewhere the convention cannot predict.

    `_conventional_destinations` covers the three destinations the framework
    documents. `mv extras/available_tools/postgresql tools/my-db` is not one of
    them, and losing track of it is the worst failure this command has: a
    silent "everything is current" while upstream fixes never arrive.

    Content is the only evidence available, and the baseline already holds it:
    a file the user has not edited still hashes to its baseline digest wherever
    it now sits. So a match is claimed ONLY when a digest names exactly one
    missing baseline file AND exactly one file on disk — anything shared (every
    empty `__init__.py`, an extra duplicated instead of moved) identifies
    nothing and is dropped. A file that was renamed AND edited cannot be found
    this way, which is why a match is recorded in the manifest the moment it is
    found: from then on the move is tracked by name, and later edits are fine.
    """
    missing: dict[str, list[str]] = {}
    claimed = set()
    for rel, digest in baseline.items():
        local = resolve(rel, moved, root)
        if os.path.isfile(os.path.join(root, local)):
            claimed.add(local)
        else:
            missing.setdefault(digest, []).append(rel)

    wanted = {d: rels[0] for d, rels in missing.items() if len(rels) == 1}
    if not wanted:
        return {}

    found: dict[str, list[str]] = {}
    for local in _project_files(root):
        if local in claimed:
            continue
        path = os.path.join(root, local)
        try:
            if os.path.getsize(path) > MAX_RENAME_CANDIDATE_BYTES:
                continue                              # not a source file
            digest = _digest(path)
        except OSError:
            continue                                  # unreadable is not a match
        if digest in wanted:
            found.setdefault(digest, []).append(local)

    matches = {wanted[d]: paths[0] for d, paths in found.items() if len(paths) == 1}
    return _generalize(root, baseline, matches)


def _common_move(src: str, dst: str) -> tuple[str, str]:
    """The shortest prefix pair that explains a file's move: the folder rename."""
    s, d = src.split("/"), dst.split("/")
    n = 0
    while n < len(s) - 1 and n < len(d) - 1 and s[-1 - n] == d[-1 - n]:
        n += 1
    return "/".join(s[:len(s) - n]), "/".join(d[:len(d) - n])


def _generalize(root: str, baseline: dict, matches: dict) -> dict:
    """
    Record the folder move rather than the file move, when that is what happened.

    A per-file record tracks only the files that existed when the folder was
    renamed — anything upstream ADDS to that extra later would land back in
    `extras/`. The folder reading is only taken when the old folder is
    genuinely vacated: if any tracked file is still sitting at its original
    path, one file moved, not the folder.
    """
    out: dict[str, str] = {}
    for src, dst in sorted(matches.items()):
        src_dir, dst_dir = _common_move(src, dst)
        vacated = src_dir != src and not any(
            rel.startswith(src_dir + "/") and os.path.isfile(os.path.join(root, rel))
            for rel in baseline
        )
        # Two files of one folder disagreeing about where it went means the
        # folder did not move as a unit.
        if vacated and out.get(src_dir, dst_dir) == dst_dir:
            out[src_dir] = dst_dir
        else:
            out.pop(src_dir, None)
            out[src] = dst
    return out


def classify(root: str, template_root: str, baseline: dict, moved: dict | None = None) -> dict:
    """Sort every upstream file into what can safely be done with it."""
    from microcoreos.scaffold import AI_KIT_ENTRIES, RUNTIME_ENTRIES

    moved = moved or {}
    upstream = _walk(template_root, RUNTIME_ENTRIES + AI_KIT_ENTRIES)
    report = {"new": [], "update": [], "conflict": [], "yours": [],
              "gone": [], "gone_yours": []}

    for rel, up_hash in sorted(upstream.items()):
        local_path = os.path.join(root, resolve(rel, moved, root))
        base_hash = baseline.get(rel)

        if not os.path.isfile(local_path):
            # Never had it, or deleted/moved it on purpose. Only offer files
            # that are genuinely new upstream.
            if base_hash is None:
                report["new"].append(rel)
            continue

        local_hash = _digest(local_path)
        if local_hash == up_hash:
            continue                                  # already current
        if base_hash is None:
            report["conflict"].append(rel)            # no baseline: cannot judge
        elif local_hash == base_hash:
            report["update"].append(rel)              # untouched → safe
        elif up_hash == base_hash:
            report["yours"].append(rel)               # your edit, upstream quiet
        else:
            report["conflict"].append(rel)            # both moved

    # Dropped upstream. The same rule as everywhere else decides what may
    # happen to it: untouched is the framework's file to withdraw, edited is
    # yours to keep.
    for rel in sorted(baseline):
        if rel in upstream:
            continue
        local_path = os.path.join(root, resolve(rel, moved, root))
        if not os.path.isfile(local_path):
            continue
        if _digest(local_path) == baseline[rel]:
            report["gone"].append(rel)
        else:
            report["gone_yours"].append(rel)

    return report


def _prune_empty_dirs(start: str, root: str) -> None:
    """
    A tool withdrawn upstream should not leave its folder behind.

    A directory holding nothing but `__pycache__` is empty as far as source
    goes — that is exactly what removing the last `.py` from a package leaves.
    """
    root = os.path.abspath(root)
    path = os.path.abspath(start)
    while path != root and path.startswith(root + os.sep):
        try:
            entries = os.listdir(path)
        except OSError:
            return
        if entries not in ([], ["__pycache__"]):
            return
        shutil.rmtree(path, ignore_errors=True)
        path = os.path.dirname(path)


def _remove(root: str, files, moved: dict) -> list[str]:
    """Delete the files upstream dropped. Returns the ones actually gone."""
    removed = []
    for rel in files:
        local = resolve(rel, moved, root)
        path = os.path.join(root, local)
        try:
            os.remove(path)
        except OSError as e:
            print(f"   ✗ {local}  — not removed ({e.strerror})")
            continue
        removed.append(rel)
        print(f"   ✗ {local}" + (f"  (upstream: {rel})" if local != rel else ""))
        _prune_empty_dirs(os.path.dirname(path), root)
    return removed


def _apply(root: str, template_root: str, files, moved: dict) -> None:
    import shutil
    for rel in files:
        local = resolve(rel, moved, root)
        dst = os.path.join(root, local)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(template_root, rel), dst)
        # The path it was WRITTEN to — an extra you installed no longer lives
        # where upstream keeps it.
        print(f"   ✓ {local}" + (f"  (upstream: {rel})" if local != rel else ""))


def advance_baseline(root: str, manifest: dict, applied, dropped=()) -> None:
    """
    Move the baseline forward for the files that were actually written, and
    drop the ones that left it — and ONLY those.

    Recomputing the whole manifest from disk would be a data-loss bug: an
    unresolved conflict would come out as `local == baseline`, i.e. "you never
    edited this", and the next `--apply` would silently overwrite the very
    edit this command refused to touch.
    """
    files = dict(manifest.get("files", {}))
    moved = dict(manifest.get("moved", {}))
    for rel in applied:
        path = os.path.join(root, resolve(rel, moved, root))
        if os.path.isfile(path):
            files[rel] = _digest(path)

    # A file upstream no longer ships has no baseline left to be: it was
    # either deleted here, or kept because you edited it — and in that case it
    # is now entirely yours. Leaving the entry would re-report it on every run
    # forever, which is how a warning gets tuned out.
    for rel in dropped:
        files.pop(rel, None)
        moved.pop(rel, None)

    os.makedirs(os.path.join(root, MANIFEST_DIR), exist_ok=True)
    with open(os.path.join(root, MANIFEST_DIR, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump({"version": version(), "files": files, "moved": moved},
                  f, indent=2, sort_keys=True)


def upgrade(argv: list[str]) -> int:
    """`microcoreos upgrade [--apply]`"""
    from microcoreos.scaffold import _template_root

    apply_changes = "--apply" in argv
    root = os.getcwd()

    if not any(os.path.isdir(os.path.join(root, d)) for d in ("tools", "domains")):
        print(
            f"[MicroCoreOS] No tools/ or domains/ directory in {root}.\n"
            "              Run this from the root of a MicroCoreOS project."
        )
        return 2

    manifest = read_manifest(root)
    if manifest is None:
        print(
            "[MicroCoreOS] No .microcoreos/manifest.json in this project.\n"
            "              That baseline is what tells your edits from a stale file,\n"
            "              and it is written by `microcoreos new`. Without it nothing\n"
            "              can be updated without risking your work."
        )
        return 1

    try:
        template_root = _template_root()
    except FileNotFoundError as e:
        print(f"[MicroCoreOS] {e}")
        return 1

    installed = version()
    print(f"\n📦 Scaffolded with {manifest.get('version', '?')} — installed {installed}\n")

    baseline = manifest.get("files", {})
    moved = dict(manifest.get("moved", {}))

    # Before classifying anything: a folder moved somewhere the convention
    # cannot predict is invisible to every check below. Recorded on sight, in
    # both modes — it is a fact about where the project's files are, not a
    # change to them, and finding it later may be impossible once the file is
    # edited.
    renamed = find_renames(root, baseline, moved)
    if renamed:
        print(f"   🔎 Found by content, now tracked ({len(renamed)}):")
        for rel, dst in sorted(renamed.items()):
            print(f"     ↳ {rel} → {dst}")
        if not record_moves(root, renamed):
            print("     (could not be written to the manifest — this report is\n"
                  "      still correct, but the next run has to find them again)")
        print()
        moved.update(renamed)
        manifest["moved"] = moved

    report = classify(root, template_root, baseline, moved)

    if report["update"]:
        print(f"   Safe to update ({len(report['update'])}) — you never edited these:")
        for rel in report["update"]:
            print(f"     · {rel}")
    if report["new"]:
        print(f"\n   New upstream ({len(report['new'])}):")
        for rel in report["new"]:
            print(f"     + {rel}")
    if report["conflict"]:
        print(f"\n   ⚠ Conflicts ({len(report['conflict'])}) — changed here AND upstream, left untouched:")
        for rel in report["conflict"]:
            print(f"     ! {rel}")
    # Withdrawals are the one class of change that reads the ABSENCE of a file
    # as an instruction, so a template that is merely incomplete looks exactly
    # like a release that deleted everything. Past a sane share of the
    # baseline, nothing is withdrawn — neither the deletions nor the releases.
    withdrawn = report["gone"] + report["gone_yours"]
    plausible = len(withdrawn) <= max(len(baseline) * MAX_REMOVAL_SHARE, 1)
    removable = report["gone"] if plausible else []
    releasable = report["gone_yours"] if plausible else []

    if not plausible:
        print(
            f"\n   ⚠ {len(withdrawn)} of {len(baseline)} baseline files are absent from"
            f" {template_root}.\n"
            "     A release does not withdraw that much — this reads as a partial or\n"
            "     broken template, so nothing will be deleted. Reinstall the package.\n"
        )
    if removable:
        print(f"\n   Removed upstream ({len(removable)}) — untouched here, safe to delete:")
        for rel in removable:
            print(f"     - {rel}")
    if releasable:
        # Reported once and then let go of: upstream does not ship it and you
        # changed it, so there is nothing left for the baseline to compare.
        # Kept in the baseline it would nag on every run, for ever.
        print(f"\n   Removed upstream but edited by you ({len(releasable)})"
              " — kept, and from now on entirely yours:")
        for rel in releasable:
            print(f"     ~ {rel}")
    if report["yours"]:
        print(f"\n   Your edits, untouched upstream ({len(report['yours'])}).")

    changeable = report["update"] + report["new"]
    if not changeable and not removable and not releasable and not report["conflict"]:
        print("   Everything is current.\n")
        return 0

    if not apply_changes:
        todo = []
        if changeable:
            todo.append(f"write the {len(changeable)} safe one(s)")
        if removable:
            todo.append(f"delete the {len(removable)} withdrawn one(s)")
        if releasable:
            todo.append(f"release the {len(releasable)} it no longer ships")
        if todo:
            print(f"\n   Run `microcoreos upgrade --apply` to {', '.join(todo)}.")
        print("   Conflicts are yours to merge by hand — nothing here overwrites them.\n")
        return 0

    if changeable:
        print(f"\n   Applying {len(changeable)} file(s):")
        _apply(root, template_root, changeable, moved)

    removed = []
    if removable:
        print(f"\n   Deleting {len(removable)} file(s) withdrawn upstream:")
        removed = _remove(root, removable, moved)

    advance_baseline(root, manifest, changeable, removed + releasable)
    print("\n   Baseline updated for those files only. Conflicts and your edits"
          " were NOT touched.\n")
    return 0
