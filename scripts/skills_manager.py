#!/usr/bin/env python3
"""Inventory a personal skill library and create missing discovery symlinks."""

import argparse
import json
import os
from pathlib import Path
import re
import sys


def absolute(value):
    return Path(os.path.abspath(Path(value).expanduser()))


def default_roots():
    home = Path.home()
    codex = Path(os.environ.get("CODEX_HOME") or home / ".codex").expanduser()
    return [home / ".agents/skills", codex / "skills", home / ".claude/skills"]


def valid_name(name):
    if len(name) > 64 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("Invalid skill name: use up to 64 lowercase letters, digits and hyphens")


def entries(root):
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if not p.name.startswith(".")), key=lambda p: p.name)


def metadata(path):
    result = {"path": str(path)}
    if path.is_symlink():
        result.update(kind="symlink", target=os.readlink(path))
        try:
            resolved = path.resolve(strict=True)
            result["has_skill_md"] = resolved.is_dir() and (resolved / "SKILL.md").is_file()
            result["status"] = "present"
        except (OSError, RuntimeError):
            result.update(status="broken-link", has_skill_md=False)
    elif path.is_dir():
        result.update(kind="directory", status="present", has_skill_md=(path / "SKILL.md").is_file())
    elif os.path.lexists(path):
        result.update(kind="file", status="present", has_skill_md=False)
    else:
        result.update(kind="missing", status="missing", has_skill_md=False)
    return result


def mount_status(path, source):
    item = metadata(path)
    if item["kind"] == "missing":
        return "missing"
    if item["kind"] == "symlink":
        if item["status"] == "broken-link":
            return "broken-link"
        return "linked" if path.resolve() == source else "conflict"
    if path.is_dir() and path.resolve() == source:
        return "canonical-directory"
    return "conflict"


def inventory(library, roots):
    library = absolute(library)
    roots = list(dict.fromkeys(absolute(root) for root in roots))
    sources = {}
    library_items = []
    for path in entries(library):
        item = {"name": path.name, **metadata(path)}
        if item["has_skill_md"]:
            sources[path.name] = path.resolve()
            item["mounts"] = [{"root": str(root), "status": mount_status(root / path.name, sources[path.name])} for root in roots]
        library_items.append(item)
    agent_items = []
    for root in roots:
        mounts = []
        for path in entries(root):
            item = {"name": path.name, **metadata(path)}
            item["managed_name"] = path.name in sources
            if path.name in sources:
                item["status"] = mount_status(path, sources[path.name])
            mounts.append(item)
        agent_items.append({"root": str(root), "root_metadata": metadata(root), "entries": mounts})
    return {"library": str(library), "library_metadata": metadata(library), "entries": library_items, "agent_roots": agent_items}


def validate_root(root):
    # A dangling root/ancestor must not silently redirect directory creation.
    for parent in (root, *root.parents):
        if os.path.lexists(parent) and not parent.is_dir():
            raise ValueError("Agent root has a non-directory or broken ancestor: " + str(parent))
    return root.resolve()


def sync(library, roots, names, all_skills=False, apply=False):
    library = absolute(library)
    if not library.is_dir():
        raise ValueError("Library must be an existing directory")
    if all_skills and names:
        raise ValueError("Choose explicit names or --all, not both")
    if all_skills:
        names = [p.name for p in entries(library) if metadata(p)["has_skill_md"]]
    elif not names:
        raise ValueError("Select at least one skill, or use --all")
    names = list(dict.fromkeys(names))
    roots = list(dict.fromkeys(validate_root(absolute(root)) for root in roots))
    if not roots:
        raise ValueError("Select at least one agent root")
    plans = []
    for name in names:
        valid_name(name)
        source = (library / name).resolve(strict=True)
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise ValueError("Selected entry is not a skill directory: " + name)
        for root in roots:
            destination = root / name
            if source in destination.parents:
                raise ValueError("A discovery link cannot be created inside its own source")
            state = mount_status(destination, source)
            plans.append({"name": name, "source": str(source), "destination": str(destination), "status": "create" if state == "missing" else state})
    report = {"apply": apply, "ok": not any(p["status"] in ("conflict", "broken-link") for p in plans), "links": plans}
    if not report["ok"] or not apply:
        return report
    for index, item in enumerate(plans):
        if item["status"] != "create":
            continue
        try:
            source = Path(item["source"])
            if not source.is_dir() or not (source / "SKILL.md").is_file():
                raise ValueError("Source disappeared before link creation")
            destination = Path(item["destination"])
            validate_root(destination.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            # No exists-then-overwrite operation: symlink fails on any entry.
            destination.symlink_to(source, target_is_directory=True)
            item["status"] = "created"
        except (OSError, ValueError, RuntimeError) as exc:
            item.update(status="failed", error=str(exc))
            for pending in plans[index + 1:]:
                if pending["status"] == "create":
                    pending["status"] = "not-applied"
            report["ok"] = False
            break
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("inventory", help="Read directory metadata and report installation state")
    linking = commands.add_parser("sync", help="Preview missing links; --apply creates them")
    for command in (listing, linking):
        command.add_argument("--library", default=str(Path.home() / "arveyskills"))
        command.add_argument("--agent-root", action="append", dest="roots")
    linking.add_argument("names", nargs="*")
    linking.add_argument("--all", action="store_true", dest="all_skills")
    linking.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        roots = default_roots() if args.roots is None else args.roots
        if args.command == "inventory":
            report = inventory(args.library, roots)
        else:
            report = sync(args.library, roots, args.names, args.all_skills, args.apply)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok", True) else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
