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
"""

import os
import json
import hashlib

MANIFEST_DIR = ".microcoreos"
MANIFEST_NAME = "manifest.json"


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


def record_move(root: str, src_rel: str, dst_rel: str) -> None:
    """Tell the baseline that an extra was moved out of extras/."""
    manifest = read_manifest(root)
    if manifest is None:
        return
    manifest.setdefault("moved", {})[src_rel] = dst_rel
    with open(os.path.join(root, MANIFEST_DIR, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)


def classify(root: str, template_root: str, baseline: dict, moved: dict | None = None) -> dict:
    """Sort every upstream file into what can safely be done with it."""
    from microcoreos.scaffold import AI_KIT_ENTRIES, RUNTIME_ENTRIES

    moved = moved or {}
    upstream = _walk(template_root, RUNTIME_ENTRIES + AI_KIT_ENTRIES)
    report = {"new": [], "update": [], "conflict": [], "yours": [], "gone": []}

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

    for rel in sorted(baseline):
        if rel not in upstream and os.path.isfile(os.path.join(root, resolve(rel, moved, root))):
            report["gone"].append(rel)

    return report


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


def advance_baseline(root: str, manifest: dict, applied) -> None:
    """
    Move the baseline forward for the files that were actually written — and
    ONLY those.

    Recomputing the whole manifest from disk would be a data-loss bug: an
    unresolved conflict would come out as `local == baseline`, i.e. "you never
    edited this", and the next `--apply` would silently overwrite the very
    edit this command refused to touch.
    """
    files = dict(manifest.get("files", {}))
    moved = manifest.get("moved", {})
    for rel in applied:
        path = os.path.join(root, resolve(rel, moved, root))
        if os.path.isfile(path):
            files[rel] = _digest(path)

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

    moved = manifest.get("moved", {})
    report = classify(root, template_root, manifest.get("files", {}), moved)

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
    if report["gone"]:
        print(f"\n   Removed upstream ({len(report['gone'])}) — still in your project:")
        for rel in report["gone"]:
            print(f"     - {rel}")
    if report["yours"]:
        print(f"\n   Your edits, untouched upstream ({len(report['yours'])}).")

    changeable = report["update"] + report["new"]
    if not changeable and not report["conflict"]:
        print("   Everything is current.\n")
        return 0

    if not apply_changes:
        if changeable:
            print(f"\n   Run `microcoreos upgrade --apply` to write the {len(changeable)} safe one(s).")
        print("   Conflicts are yours to merge by hand — nothing here overwrites them.\n")
        return 0

    print(f"\n   Applying {len(changeable)} file(s):")
    _apply(root, template_root, changeable, moved)
    advance_baseline(root, manifest, changeable)
    print("\n   Baseline updated for those files only. Conflicts were NOT touched.\n")
    return 0
