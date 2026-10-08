#!/usr/bin/env python3
"""Preview or apply an explicit skill consolidation manifest without overwrites."""

import argparse
import ctypes
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import uuid


PRIVATE_DIRS = {".git", ".aws", ".ssh", ".gnupg", "secrets", "secret", "credentials", "credential", "__pycache__", "node_modules", ".cache", "cache", "caches", ".pytest_cache", ".venv", "venv"}
PRIVATE_FILES = {"id_rsa", "id_ed25519", "id_ecdsa", "id_dsa", "credentials", "credential", "config.json", ".npmrc", ".pypirc", ".netrc", ".skill-lock.json", "auth.json", ".auth.json", "auth-profiles.json", ".auth-profiles.json"}
PRIVATE_TOKENS = {"config", "credential", "secret", "token", "password", "cookie", "private_key", "private-key"}
PRIVATE_DIR_NAMES = {name.lstrip(".") for name in PRIVATE_DIRS}


def absolute(value):
    return Path(os.path.abspath(Path(value).expanduser()))


def inside(path, root):
    return path == root or root in path.parents


def fingerprint(root):
    """Hash structure, modes, sizes and safe file contents; never follow links."""
    digest = hashlib.sha256()
    for current, directories, files in os.walk(root, followlinks=False):
        current = Path(current)
        paths = [current] + [current / name for name in sorted(directories + files)]
        for path in paths:
            relative = path.relative_to(root)
            info = path.lstat()
            record = [str(relative), stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode)]
            if path.is_symlink():
                record.append(os.readlink(path))
            elif path.is_file():
                record.append(info.st_size)
                private = any(part.lower().lstrip(".") in PRIVATE_DIR_NAMES or part.lower().startswith(".env") or any(token in part.lower() for token in PRIVATE_TOKENS) for part in relative.parts) or path.name.lower() in PRIVATE_FILES or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
                if not private:
                    content = hashlib.sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            content.update(chunk)
                    record.append(content.hexdigest())
            digest.update(json.dumps(record, separators=(",", ":")).encode())
        directories[:] = sorted(name for name in directories if name != ".git" and not (current / name).is_symlink())
    return digest.hexdigest()


def inspect_links(source):
    for current, directories, files in os.walk(source, followlinks=False):
        for name in directories + files:
            path = Path(current) / name
            if name == ".git" and not path.is_dir():
                raise ValueError("Git worktree/submodule metadata cannot be relocated safely: " + str(path))
            if path.is_symlink() and not os.path.isabs(os.readlink(path)):
                if not inside(path.resolve(), source):
                    raise ValueError("External relative symlink would break when moved: " + str(path))


def validate_parent(path):
    for parent in (path.parent, *path.parent.parents):
        if os.path.lexists(parent) and not parent.is_dir():
            raise ValueError("Non-directory or broken ancestor: " + str(parent))


def rename_without_replace(source, destination):
    """Use native exclusive rename; a concurrent destination must never be lost."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        operation = libc.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = operation(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        operation = libc.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = operation(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise OSError(errno.ENOTSUP, "Exclusive directory rename is unavailable")
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def plan(manifest):
    library = absolute(manifest["library"])
    validate_parent(library)
    if os.path.lexists(library) and (library.is_symlink() or not library.is_dir()):
        raise ValueError("Library must be a real directory")
    library = library.resolve()
    rows = []
    for entry in manifest["entries"]:
        source = absolute(entry["source"])
        target = absolute(entry["target"])
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Source must be a real directory: " + str(source))
        source = source.resolve()
        children = entry.get("skills")
        if children is not None:
            if not isinstance(children, list) or not children:
                raise ValueError("Package skills must be an explicit nonempty list")
            for child in children:
                relative = Path(child)
                selected = (source / relative).resolve()
                if relative.is_absolute() or not inside(selected, source) or not (selected / "SKILL.md").is_file():
                    raise ValueError("Package skill must stay inside its source and contain SKILL.md")
        elif not (source / "SKILL.md").is_file():
            raise ValueError("Source has no root SKILL.md; packages require explicit skills")
        if os.path.lexists(target):
            raise ValueError("Target already exists: " + str(target))
        validate_parent(target)
        target = target.resolve()
        if target == library or not inside(target, library) or ".backups" in target.relative_to(library).parts:
            raise ValueError("Target must be inside the library, outside .backups")
        if inside(target, source) or inside(source, target) or inside(library, source):
            raise ValueError("Source and target/library cannot contain each other")
        for row in rows:
            previous_source, previous_target = Path(row["source"]), Path(row["target"])
            if any(inside(a, b) or inside(b, a) for a, b in ((source, previous_source), (target, previous_target), (source, previous_target), (target, previous_source))):
                raise ValueError("Manifest has overlapping sources or destinations")
        inspect_links(source)
        row = {"source": str(source), "target": str(target), "status": "planned", "fingerprint_before": fingerprint(source)}
        if children is not None:
            row["skills"] = children
        rows.append(row)
    report_path = absolute(manifest["report_path"]) if manifest.get("report_path") else None
    if report_path:
        validate_parent(report_path)
        if os.path.lexists(report_path) or inside(library, report_path.resolve()) or any(inside(report_path.resolve(), Path(row[key])) for row in rows for key in ("source", "target")):
            raise ValueError("Report must be a new file outside selected skills")
    backups = library / ".backups"
    if os.path.lexists(backups) and (backups.is_symlink() or not backups.is_dir()):
        raise ValueError("Backup root must be a real directory")
    return library, rows, report_path


def consolidate(manifest, apply=False):
    library, rows, report_path = plan(manifest)
    report = {"library": str(library), "apply": apply, "ok": True, "entries": rows}
    if not apply or not rows:
        return report
    run = library / ".backups" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:12])
    run.mkdir(parents=True, exist_ok=False)
    report["backup_root"] = str(run)
    for index, row in enumerate(rows):
        source, target = Path(row["source"]), Path(row["target"])
        backup = run / (str(index) + "-" + source.name)
        moved = False
        try:
            if source.is_symlink() or fingerprint(source) != row["fingerprint_before"]:
                raise ValueError("Source changed after validation")
            if os.path.lexists(target):
                raise ValueError("Destination appeared after validation")
            shutil.copytree(source, backup, symlinks=True, copy_function=shutil.copy2)
            row["backup"] = str(backup)
            if fingerprint(backup) != row["fingerprint_before"] or fingerprint(source) != row["fingerprint_before"]:
                raise ValueError("Backup/source verification failed")
            target.parent.mkdir(parents=True, exist_ok=True)
            rename_without_replace(source, target)
            moved = True
            source.symlink_to(target, target_is_directory=True)
            row["fingerprint_after"] = fingerprint(target)
            if row["fingerprint_after"] != row["fingerprint_before"] or source.resolve() != target:
                raise ValueError("Post-move verification failed")
            row["status"] = "moved-and-linked"
        except (OSError, ValueError, RuntimeError) as exc:
            row.update(status="failed", error=str(exc))
            if moved:
                try:
                    if source.is_symlink() and os.readlink(source) == str(target):
                        source.unlink()
                    rename_without_replace(target, source)
                    row["recovery"] = "restored-original"
                except OSError as recovery_error:
                    row["recovery_error"] = str(recovery_error)
            for pending in rows[index + 1:]:
                pending["status"] = "not-applied"
            report["ok"] = False
            break
    if report_path:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            with report_path.open("x") as handle:
                json.dump(report, handle, indent=2)
                handle.write("\n")
        except OSError as exc:
            report.update(ok=False, report_error=str(exc))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="JSON with library, source/target entries and optional report_path")
    parser.add_argument("--apply", action="store_true", help="Back up, move and link selected sources")
    args = parser.parse_args(argv)
    try:
        with Path(args.manifest).open() as handle:
            report = consolidate(json.load(handle), args.apply)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        report = {"ok": False, "apply": args.apply, "error": str(exc)}
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
