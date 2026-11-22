"""Install and activate extras published outside the MicroCoreOS catalog.

External extras use a ``microcoreos-extra.toml`` manifest at their repository
root. Installation copies only the declared components into
``extras/installed/<name>``. Activation later copies those components into the
Kernel's discovery roots; the staged original remains available for inspection.

Manifest format::

    name = "mail"
    python_dependencies = ["some-mail-client>=1"]

    [environment]
    MAIL_HOST = "localhost"

    [[components]]
    kind = "domain" # tool | domain | driver
    source = "domains/mail"
    target = "mail"

Tool/domain targets are Python package identifiers. Driver targets are file
names ending in ``_driver.py`` and land under ``tools/event_bus/``.
"""

from __future__ import annotations

import json
import keyword
import os
import re
import shutil
import shlex
import subprocess
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from microcoreos.catalog import _append_env
from microcoreos.project import looks_like_a_project

MANIFEST = "microcoreos-extra.toml"
INSTALL_META = ".microcoreos-install.json"
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DRIVER = re.compile(r"^[a-z][a-z0-9_]*_driver\.py$")
_TOP_LEVEL_KEYS = {"name", "python_dependencies", "environment", "components"}


class ExtraError(ValueError):
    """A source or installed extra does not meet the external-extra contract."""


def _safe_source(source: str) -> str:
    """Avoid persisting embedded URL credentials in install metadata."""
    if "://" in source:
        parsed = urlsplit(source)
        host = parsed.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    # SCP-style SSH URLs have no password field, but the username may still be
    # a credential. Keep only the host and repository path.
    if "@" in source and ":" in source and not os.path.exists(source):
        _, remainder = source.split("@", 1)
        return f"ssh://{remainder}"
    return "local"


def _project_root() -> Path:
    root = Path.cwd().resolve()
    if not looks_like_a_project(str(root)):
        raise ExtraError(
            f"No tools/ or domains/ directory in {root}. "
            "Run this from the root of a MicroCoreOS project."
        )
    return root


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _source_path(root: Path, value: object, *, kind: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ExtraError(f"Invalid component source path: {value!r}")
    relative = PurePosixPath(value)
    if not relative.parts or relative.is_absolute() or any(
        part in ("", ".", "..") for part in relative.parts
    ):
        raise ExtraError(f"Component source must be a safe relative path: {value!r}")
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise ExtraError(f"Component source cannot be a symlink: {value}")
    resolved = candidate.resolve()
    if not _inside(root, resolved):
        raise ExtraError(f"Component source escapes the source repository: {value}")
    if kind == "driver":
        if not resolved.is_file():
            raise ExtraError(f"Driver source is not a file: {value}")
    elif not resolved.is_dir():
        raise ExtraError(f"Component source is not a directory: {value}")

    # Do not let a source package smuggle an external tree through a nested
    # symlink; symlink support differs between platforms and can escape staging.
    if resolved.is_dir():
        for current, dirs, files in os.walk(resolved, followlinks=False):
            for child in dirs + files:
                if (Path(current) / child).is_symlink():
                    raise ExtraError(f"Symlinks are not supported in components: {value}")
    return resolved


def _load_manifest(source_root: Path) -> dict:
    manifest_path = source_root / MANIFEST
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ExtraError(f"Source must contain {MANIFEST} at its root.")
    try:
        document = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ExtraError(f"Cannot read {MANIFEST}: {exc}") from exc

    if not isinstance(document, dict):
        raise ExtraError(f"{MANIFEST} must contain a TOML table.")
    unknown = sorted(set(document) - _TOP_LEVEL_KEYS)
    if unknown:
        raise ExtraError(f"Unknown {MANIFEST} keys: {', '.join(unknown)}")

    name = document.get("name")
    if not isinstance(name, str) or len(name) > 64 or not _NAME.fullmatch(name):
        raise ExtraError("Manifest `name` must be 1-64 characters matching [a-z][a-z0-9_]*.")

    dependencies = document.get("python_dependencies", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(item, str) or not item or item != item.strip()
        or item.startswith("-") or any(ch in item for ch in "\r\n\x00")
        for item in dependencies
    ):
        raise ExtraError("`python_dependencies` must be an array of package specifications.")

    environment = document.get("environment", {})
    if not isinstance(environment, dict) or any(
        not isinstance(key, str) or not _ENV_NAME.fullmatch(key)
        or not isinstance(value, str) or any(ch in value for ch in "\r\n\x00")
        for key, value in environment.items()
    ):
        raise ExtraError("`environment` must map valid variable names to string defaults.")

    components = document.get("components")
    if not isinstance(components, list) or not components:
        raise ExtraError("`components` must declare at least one tool, domain, or driver.")

    parsed = []
    source_roots: list[Path] = []
    destinations: set[tuple[str, str]] = set()
    destination_paths: list[PurePosixPath] = []
    for index, component in enumerate(components):
        if not isinstance(component, dict) or set(component) != {"kind", "source", "target"}:
            raise ExtraError(
                f"Component {index + 1} must contain exactly kind, source, and target."
            )
        kind, source_value, target = (
            component["kind"], component["source"], component["target"]
        )
        if kind not in ("tool", "domain", "driver"):
            raise ExtraError(f"Component {index + 1} has unsupported kind {kind!r}.")
        if not isinstance(target, str):
            raise ExtraError(f"Component {index + 1} target must be a string.")
        if kind in ("tool", "domain"):
            if len(target) > 64 or not target.isascii() or not target.isidentifier() or keyword.iskeyword(target):
                raise ExtraError(f"{kind} target must be a Python package identifier: {target!r}")
        elif not _DRIVER.fullmatch(target):
            raise ExtraError(f"Driver target must be a filename ending in _driver.py: {target!r}")

        path = _source_path(source_root, source_value, kind=kind)
        if kind == "tool" and not any(path.rglob("*_tool.py")):
            raise ExtraError(f"Tool component {source_value!r} contains no *_tool.py file.")
        if kind == "domain" and not any(path.rglob("*_plugin.py")):
            raise ExtraError(f"Domain component {source_value!r} contains no *_plugin.py file.")
        if kind == "driver" and not path.name.endswith("_driver.py"):
            raise ExtraError(f"Driver source must end in _driver.py: {source_value!r}")

        key = (kind, target)
        if key in destinations:
            raise ExtraError(f"Duplicate component destination: {kind}/{target}")
        destinations.add(key)
        if kind == "tool":
            destination_path = PurePosixPath("tools", target)
        elif kind == "domain":
            destination_path = PurePosixPath("domains", target)
        else:
            destination_path = PurePosixPath("tools", "event_bus", target)
        for previous in destination_paths:
            if destination_path == previous or destination_path in previous.parents or previous in destination_path.parents:
                raise ExtraError("Component destination paths cannot overlap.")
        destination_paths.append(destination_path)
        for previous in source_roots:
            if _inside(previous, path) or _inside(path, previous):
                raise ExtraError("Component source paths cannot overlap.")
        source_roots.append(path)
        parsed.append({"kind": kind, "source": source_value, "target": target})

    return {
        "name": name,
        "python_dependencies": dependencies,
        "environment": environment,
        "components": parsed,
    }


def _git_source(source: str, ref: str | None) -> tuple[Path, str | None]:
    if ref is not None and (
        not ref or ref.startswith("-") or ref != ref.strip()
        or any(ord(ch) < 32 for ch in ref)
    ):
        raise ExtraError("Git ref must be a non-empty ref name, tag, or commit.")
    temporary = Path(tempfile.mkdtemp(prefix="microcoreos-extra-source-"))
    checkout = temporary / "checkout"
    try:
        result = subprocess.run(
            ["git", "clone", "--quiet", "--", source, str(checkout)],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ExtraError(f"Git could not fetch the extra (exit {result.returncode}).")
        if ref:
            result = subprocess.run(
                ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", ref],
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode:
                raise ExtraError(f"Git could not resolve requested ref (exit {result.returncode}).")
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ExtraError("Git could not resolve the checked out commit.")
        return checkout, result.stdout.strip()
    except FileNotFoundError as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        raise ExtraError("Git is required to install an extra from a repository URL.") from exc
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def install(source: str, ref: str | None = None) -> int:
    """Validate and stage a local or Git extra without activating its code."""
    root = _project_root()
    local = Path(source).expanduser()
    git_source = not local.is_dir()
    if ref is not None and not git_source:
        raise ExtraError("`--ref` can only be used with a Git source.")

    checkout = None
    git_temp = None
    if git_source:
        checkout, commit = _git_source(source, ref)
        git_temp = checkout.parent
    else:
        checkout = local.resolve()
        commit = None
        if (checkout / ".git").exists():
            try:
                result = subprocess.run(
                    ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if result.returncode == 0:
                    commit = result.stdout.strip()
            except FileNotFoundError:
                pass

    stage_parent = root / "extras" / "installed"
    if (root / "extras").is_symlink() or stage_parent.is_symlink():
        if git_temp is not None:
            shutil.rmtree(git_temp, ignore_errors=True)
        raise ExtraError("The extras installation path cannot contain symlinks.")
    temp_stage: Path | None = None
    try:
        manifest = _load_manifest(checkout)
        destination = stage_parent / manifest["name"]
        if _inside(checkout.resolve(), destination.resolve()):
            raise ExtraError("The project cannot install itself as an external extra.")
        if destination.exists() or destination.is_symlink():
            raise ExtraError(f"Extra {manifest['name']!r} is already installed; left untouched.")

        stage_parent.mkdir(parents=True, exist_ok=True)
        temp_stage = Path(tempfile.mkdtemp(prefix=f".{manifest['name']}-", dir=stage_parent))
        shutil.copy2(checkout / MANIFEST, temp_stage / MANIFEST)
        for component in manifest["components"]:
            relative = PurePosixPath(component["source"])
            source_path = checkout.joinpath(*relative.parts)
            staged_path = temp_stage.joinpath(*relative.parts)
            staged_path.parent.mkdir(parents=True, exist_ok=True)
            if component["kind"] == "driver":
                shutil.copy2(source_path, staged_path)
            else:
                shutil.copytree(source_path, staged_path)

        metadata = {
            "source": _safe_source(source),
            "ref": ref,
            "commit": commit,
            "enabled": False,
        }
        (temp_stage / INSTALL_META).write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temp_stage, destination)
        temp_stage = None
        print(f"   Installed inactive extra {manifest['name']!r} in extras/installed/{manifest['name']}/")
        if commit:
            print(f"   Git commit: {commit}")
        print(f"   Activate later with: microcoreos extra enable {manifest['name']}")
        return 0
    finally:
        if temp_stage is not None:
            shutil.rmtree(temp_stage, ignore_errors=True)
        if git_temp is not None:
            shutil.rmtree(git_temp, ignore_errors=True)


def _destinations(root: Path, manifest: dict) -> list[tuple[Path, Path]]:
    staged = root / "extras" / "installed" / manifest["name"]
    results = []
    for component in manifest["components"]:
        source = staged.joinpath(*PurePosixPath(component["source"]).parts)
        if component["kind"] == "tool":
            destination = root / "tools" / component["target"]
        elif component["kind"] == "domain":
            destination = root / "domains" / component["target"]
        else:
            destination = root / "tools" / "event_bus" / component["target"]
        results.append((source, destination))
    return results


def enable(name: str, no_install: bool = False) -> int:
    """Copy a staged extra into the active discovery roots."""
    root = _project_root()
    if len(name) > 64 or not _NAME.fullmatch(name):
        raise ExtraError(f"Invalid extra name: {name!r}")
    staged = root / "extras" / "installed" / name
    if not staged.is_dir() or staged.is_symlink():
        raise ExtraError(f"Extra {name!r} is not installed under extras/installed/.")
    manifest = _load_manifest(staged)
    if manifest["name"] != name:
        raise ExtraError("Installed folder name does not match the manifest name.")

    metadata_path = staged / INSTALL_META
    if metadata_path.is_symlink():
        raise ExtraError("Installed extra metadata cannot be a symlink.")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExtraError(f"Installed extra metadata is missing or invalid: {exc}") from exc
    if not isinstance(metadata, dict) or not isinstance(metadata.get("enabled"), bool):
        raise ExtraError("Installed extra metadata is invalid.")

    pairs = _destinations(root, manifest)
    missing_sources = [str(source) for source, _ in pairs if not source.exists()]
    if missing_sources:
        raise ExtraError("Installed component source is missing: " + ", ".join(missing_sources))
    for _, destination in pairs:
        current = root
        for part in destination.relative_to(root).parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ExtraError(f"Activation path cannot traverse a symlink: {current.relative_to(root)}")
            if current.exists() and not current.is_dir():
                raise ExtraError(f"Activation path is not a directory: {current.relative_to(root)}")
    existing = [
        str(destination.relative_to(root))
        for _, destination in pairs
        if destination.exists() or destination.is_symlink()
    ]
    if existing:
        if metadata["enabled"] and len(existing) == len(pairs):
            print(f"   Extra {name!r} is already enabled.")
            return 0
        raise ExtraError("Activation would overwrite existing paths: " + ", ".join(existing))

    dependencies = manifest["python_dependencies"]
    if dependencies and no_install:
        print("   Dependencies were not installed; add them manually:")
        print("   " + shlex.join(["uv", "add", *dependencies]))
    elif dependencies:
        if not (root / "pyproject.toml").is_file():
            raise ExtraError("Cannot install dependencies without pyproject.toml; use --no-install to manage them manually.")
        if shutil.which("uv") is None:
            raise ExtraError("uv was not found; install dependencies manually or use --no-install.")
        result = subprocess.run(["uv", "add", *dependencies], cwd=root, check=False)
        if result.returncode:
            raise ExtraError(f"uv add failed with exit code {result.returncode}; extra was not activated.")

    created: list[Path] = []
    try:
        for source, destination in pairs:
            destination.parent.mkdir(parents=True, exist_ok=True)
            created.append(destination)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)

        env_values = manifest["environment"]
        _append_env(
            str(root),
            name,
            [(key, value, None) for key, value in env_values.items()],
            command="extra enable",
        )
        metadata["enabled"] = True
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    except Exception:
        for path in reversed(created):
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                try:
                    path.unlink()
                except OSError:
                    pass
        raise

    print(f"   Enabled extra {name!r} by copying its components into the active project.")
    print("   The installed source remains in extras/installed/.")
    return 0


def list_extras() -> int:
    """List external extras staged under extras/installed/."""
    root = _project_root()
    stage_parent = root / "extras" / "installed"
    if not stage_parent.is_dir():
        print("No external extras installed.")
        return 0

    entries = sorted(
        p for p in stage_parent.iterdir()
        if p.is_dir() and not p.is_symlink() and not p.name.startswith(".")
    )
    if not entries:
        print("No external extras installed.")
        return 0

    for entry in entries:
        meta_path = entry / INSTALL_META
        status = "unknown"
        details: list[str] = []
        if meta_path.is_file() and not meta_path.is_symlink():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(meta, dict):
                    enabled = meta.get("enabled")
                    if enabled is True:
                        status = "enabled"
                    elif enabled is False:
                        status = "inactive"
                    if meta.get("source"):
                        details.append(f"source={meta['source']}")
                    if meta.get("ref"):
                        details.append(f"ref={meta['ref']}")
                    if meta.get("commit"):
                        details.append(f"commit={str(meta['commit'])[:12]}")
            except (OSError, UnicodeError, json.JSONDecodeError):
                status = "invalid metadata"
        suffix = ("  " + "  ".join(details)) if details else ""
        print(f"  {entry.name}  [{status}]{suffix}")
    return 0


USAGE = """Usage:
  microcoreos extra install <local-path|git-url> [--ref <ref>]
  microcoreos extra enable <name> [--no-install]
  microcoreos extra list

Install stages an inactive extra. Enable copies its declared components to
tools/, domains/, or tools/event_bus/ and applies its dependencies and .env defaults.
"""


def command(argv: list[str]) -> int:
    """Dispatch the `microcoreos extra` subcommands without shell parsing."""
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    action, args = argv[0], argv[1:]
    if action == "install":
        if not args:
            print(USAGE)
            return 2
        if args[0] in ("-h", "--help"):
            print(USAGE)
            return 0
        if args[0].startswith("-"):
            print(USAGE)
            return 2
        source, *options = args
        ref = None
        index = 0
        while index < len(options):
            if options[index] == "--ref" and index + 1 < len(options) and ref is None:
                ref = options[index + 1]
                index += 2
            elif options[index] in ("-h", "--help"):
                print(USAGE)
                return 0
            else:
                print(f"Unknown extra install option: {options[index]}\n\n{USAGE}")
                return 2
        try:
            return install(source, ref)
        except ExtraError as exc:
            print(f"[MicroCoreOS] {exc}")
            return 2
        except OSError as exc:
            print(f"[MicroCoreOS] Could not install the extra: {exc}")
            return 2
    if action == "enable":
        if "-h" in args or "--help" in args:
            print(USAGE)
            return 0
        no_install = "--no-install" in args
        positional = [arg for arg in args if not arg.startswith("-")]
        if len(positional) != 1 or any(
            arg != "--no-install" for arg in args if arg.startswith("-")
        ):
            print(USAGE)
            return 2
        try:
            return enable(positional[0], no_install=no_install)
        except ExtraError as exc:
            print(f"[MicroCoreOS] {exc}")
            return 2
        except OSError as exc:
            print(f"[MicroCoreOS] Could not enable the extra: {exc}")
            return 2
    if action == "list":
        if "-h" in args or "--help" in args:
            print(USAGE)
            return 0
        if args:
            print(USAGE)
            return 2
        try:
            return list_extras()
        except ExtraError as exc:
            print(f"[MicroCoreOS] {exc}")
            return 2
        except OSError as exc:
            print(f"[MicroCoreOS] Could not list extras: {exc}")
            return 2
    print(f"Unknown extra operation: {action}\n\n{USAGE}")
    return 2
