#!/usr/bin/env python3
"""Inventory a personal skill library, validate skill content, and create missing links."""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.parse


SCHEMA_VERSION = 1
SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    ".venv", "venv", "node_modules", ".tox", ".cache",
    "vendor", "dist", "build", "coverage", ".next",
}
TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".py", ".sh", ".bash", ".zsh",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf",
    ".html", ".css", ".js", ".ts", ".tsx", ".jsx",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SENSITIVE_DIRS = {"secrets", ".secrets", ".ssh", ".aws"}
MAX_TEXT_BYTES = 512 * 1024
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
REF_LINK_RE = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)")
HOST_PATH_RE = re.compile(r"(?<![\w.-])/(?:Users|home)/[A-Za-z0-9._-]+/")
STALE_RE = re.compile(
    r"(?im)^\s*(?:last[_-]?validated|validated[_-]?on)\s*:\s*(\d{4}-\d{2}-\d{2})\s*$"
)
PLACEHOLDER_RE = re.compile(
    r"^(?:<.*>|\$\{.*\}|x{4,}|\*{4,}|redacted|example|placeholder|changeme|replace.*)$",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    ("aws_access_key", "error", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", "error", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----")),
    ("mysql_dsn", "error", re.compile(r"(?i)\bmysqlDsn\b\s*[:=]\s*[\"']?([^\s\"']{8,})")),
    ("tos_credential", "error", re.compile(r"(?i)\b(?:tosAccessKey|tosSecretKey)\b\s*[:=]\s*[\"']?([^\s\"']{8,})")),
    ("cloud_key", "error", re.compile(r"(?i)\b(?:access_key_id|secret_access_key)\b\s*[:=]\s*[\"']?([A-Za-z0-9/+=]{16,})")),
    ("literal_secret", "info", re.compile(r"(?i)\b(?:password|passwd|secret|token)\b\s*[:=]\s*[\"']([^\"']{8,})[\"']")),
)


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def path_inside(path, root):
    """Return True only when both paths are resolved and path is under root."""
    try:
        return path == root or root in path.parents
    except (OSError, RuntimeError):
        return False


def strip_yaml_comment(value):
    """Drop a YAML comment outside quotes, keeping # inside quoted values."""
    quote = None
    output = []
    for index, char in enumerate(value):
        if quote is not None:
            output.append(char)
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
            output.append(char)
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            break
        else:
            output.append(char)
    return "".join(output).rstrip()


def absolute(value):
    return Path(os.path.abspath(Path(value).expanduser()))


def default_library():
    return Path.home() / "skills-manager"


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


def skill_file_ok(path):
    candidate = path / "SKILL.md"
    try:
        return candidate.is_file() and candidate.stat().st_size > 0
    except OSError:
        return False


def source_kind(path):
    if path.is_symlink():
        return "alias"
    try:
        if (path / ".git").exists():
            return "git"
    except OSError:
        pass
    return "owned"


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
        item = {"name": path.name, **metadata(path), "source_kind": source_kind(path)}
        if item["has_skill_md"]:
            sources[path.name] = path.resolve()
            item["mounts"] = [
                {"root": str(root), "status": mount_status(root / path.name, sources[path.name])}
                for root in roots
            ]
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
    conflicts = sum(
        1
        for item in agent_items
        for mount in item["entries"]
        if mount.get("status") in ("conflict", "broken-link")
    )
    broken = sum(
        1 for item in library_items if item.get("status") in ("broken-link", "missing")
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "library": str(library),
        "library_metadata": metadata(library),
        "ok": conflicts == 0 and broken == 0,
        "counts": {
            "entries": len(library_items),
            "skills": sum(1 for item in library_items if item["has_skill_md"]),
            "conflicts": conflicts,
            "broken": broken,
        },
        "entries": library_items,
        "agent_roots": agent_items,
    }


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
    warnings = []
    if all_skills:
        names = [p.name for p in entries(library) if metadata(p)["has_skill_md"]]
        aliases = [name for name in names if (library / name).is_symlink()]
        if aliases:
            warnings.append(
                "--all includes %d alias entries; use explicit names to limit scope" % len(aliases)
            )
    elif not names:
        raise ValueError("Select at least one skill, or use --all")
    names = list(dict.fromkeys(names))
    roots = list(dict.fromkeys(validate_root(absolute(root)) for root in roots))
    if not roots:
        raise ValueError("Select at least one agent root")
    plans = []
    for name in names:
        valid_name(name)
        entry = library / name
        if not os.path.lexists(entry):
            raise FileNotFoundError("Selected entry does not exist: " + name)
        source = entry.resolve(strict=True)
        if not source.is_dir() or not skill_file_ok(source):
            raise ValueError("Selected entry is not a skill directory with a non-empty SKILL.md: " + name)
        for root in roots:
            destination = root / name
            if source in destination.parents:
                raise ValueError("A discovery link cannot be created inside its own source")
            state = mount_status(destination, source)
            plans.append({
                "name": name,
                "source": str(source),
                "source_kind": source_kind(entry),
                "destination": str(destination),
                "status": "create" if state == "missing" else state,
            })
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "apply": apply,
        "ok": not any(p["status"] in ("conflict", "broken-link") for p in plans),
        "warnings": warnings,
        "links": plans,
    }
    if not report["ok"] or not apply:
        return report
    for index, item in enumerate(plans):
        if item["status"] != "create":
            continue
        try:
            source = Path(item["source"])
            if not source.is_dir() or not skill_file_ok(source):
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


# ---------------------------------------------------------------------------
# Content checks. This command is deliberately read-only and offline.
# ---------------------------------------------------------------------------


def issue(severity, code, message, file=None, line=None, **extra):
    item = {"severity": severity, "code": code, "message": message}
    if file is not None:
        item["file"] = str(file)
    if line is not None:
        item["line"] = line
    item.update(extra)
    return item


def parse_frontmatter(text):
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return "missing", {}
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return "unclosed", {}
    data = {}
    index = 1
    while index < end:
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", lines[index])
        if not match:
            index += 1
            continue
        key, value = match.group(1), match.group(2).strip()
        if value in (">", ">-", ">+", "|", "|-", "|+"):
            block = []
            index += 1
            while index < end and (
                lines[index].startswith(" ") or lines[index].startswith("\t") or not lines[index].strip()
            ):
                if lines[index].strip():
                    block.append(lines[index].strip())
                index += 1
            data[key] = ("\n" if value.startswith("|") else " ").join(block)
            continue
        value = strip_yaml_comment(value)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        data[key] = value
        index += 1
    return "ok", data


def strip_code(text):
    """Remove fenced and inline code so example links are not treated as real links."""
    output = []
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            output.append(line)
    joined = "\n".join(output)
    return re.sub(r"`[^`]*`", "", joined)


def link_targets(text):
    stripped = strip_code(text)
    for match in LINK_RE.finditer(stripped):
        target = match.group(1).strip()
        if target.startswith("<") and ">" in target:
            target = target[1:target.index(">")]
        else:
            target = target.split()[0] if target else target
        yield target
    for line in stripped.splitlines():
        match = REF_LINK_RE.match(line)
        if match:
            yield match.group(1)


def is_sensitive(path):
    name = path.name.lower()
    if name.startswith(".env"):
        return not name.endswith((".example", ".sample", ".template"))
    if name.endswith(("_token", ".token")):
        return True
    if name in {"credentials", "credentials.json", "id_rsa", "id_ed25519"}:
        return True
    if path.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    return any(part.lower() in SENSITIVE_DIRS for part in path.parts)


def walk_entries(root):
    """Yield files and symlinks without following symlinked directories."""
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        linked_dirs = [name for name in dirs if (current_path / name).is_symlink()]
        dirs[:] = sorted(
            name for name in dirs
            if name not in SKIP_DIRS and name not in linked_dirs
        )
        for name in sorted(linked_dirs):
            yield current_path / name
        for name in sorted(files):
            yield current_path / name


def walk_files(root):
    for path in walk_entries(root):
        if not path.is_symlink():
            yield path


def text_files(root):
    for path in walk_files(root):
        if is_sensitive(path):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"Dockerfile", "Makefile"}:
            continue
        try:
            if path.stat().st_size > MAX_TEXT_BYTES:
                continue
        except OSError:
            continue
        yield path


def read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def line_number(text, offset):
    return text.count("\n", 0, offset) + 1


def placeholder(value):
    value = value.strip().strip("'\"")
    return not value or bool(PLACEHOLDER_RE.match(value))


def check_skill(root, stale_days=90, secrets=True, expected_name=None, is_alias=False, publish=False):
    issues = []
    root_resolved = root.resolve()
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        return [issue("error", "skill_missing", "SKILL.md is missing")]
    text = read_text(skill_md)
    if not text.strip():
        return [issue("error", "skill_empty", "SKILL.md is empty")]

    severity = "error" if publish or not is_alias else "warning"
    status, frontmatter = parse_frontmatter(text)
    if status == "missing":
        issues.append(issue(
            severity, "frontmatter_missing", "SKILL.md has no YAML frontmatter"
        ))
    elif status == "unclosed":
        issues.append(issue(
            severity, "frontmatter_unclosed", "SKILL.md frontmatter is not closed"
        ))
    else:
        name = (frontmatter.get("name") or "").strip()
        description = (frontmatter.get("description") or "").strip()
        if not name:
            issues.append(issue(severity, "name_missing", "frontmatter has no name"))
        else:
            allowed = {root.name}
            if expected_name:
                allowed.add(expected_name)
            if name not in allowed:
                alias_only = is_alias and not publish
                issues.append(issue(
                    "warning" if alias_only else "error",
                    "name_mismatch_alias" if alias_only else "name_mismatch",
                    "frontmatter name %r does not match directory %r" % (name, root.name),
                ))
            try:
                valid_name(name)
            except ValueError as exc:
                issues.append(issue("error", "name_invalid", str(exc)))
        if not description:
            issues.append(issue(
                severity, "description_missing", "frontmatter has no description"
            ))
        elif len(description) < 8:
            issues.append(issue("warning", "description_short", "description is very short"))

    # Markdown links and host-specific paths.
    markdown_files = [skill_md] + [
        p for p in text_files(root)
        if p != skill_md and p.suffix.lower() in (".md", ".markdown")
    ]
    for path in markdown_files:
        content = read_text(path)
        relative = path.relative_to(root)
        for target in link_targets(content):
            if not target or target.startswith(("#", "//", "?")):
                continue
            if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            if target.startswith(("/", "~")):
                issues.append(issue(
                    "error" if publish else "info", "link_absolute_host",
                    "link target is host-specific; use a relative path",
                    relative, pattern=target,
                ))
                continue
            clean = urllib.parse.unquote(target.split("#", 1)[0])
            if not clean:
                continue
            try:
                candidate = (path.parent / clean).resolve()
                exists = candidate.exists()
            except (OSError, RuntimeError):
                candidate = None
                exists = False
            if publish and candidate is not None and not path_inside(candidate, root_resolved):
                issues.append(issue(
                    "error", "link_outside_skill",
                    "relative link resolves outside the skill; vendored content is required for publish",
                    relative, pattern=target,
                ))
                continue
            if not exists:
                issues.append(issue(
                    "error", "link_broken", "relative link target does not exist",
                    relative, pattern=target,
                ))

    # File modes and host paths.
    for path in walk_files(root):
        relative = path.relative_to(root)
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            continue
        if mode & 0o044 == 0 and not is_sensitive(path):
            issues.append(issue(
                "warning", "permissions",
                "file is not group/other readable (%s)" % oct(mode), relative,
            ))
        if is_sensitive(path):
            issues.append(issue(
                "warning", "secret_file",
                "sensitive file inside a skill; remove or reference a secret store", relative,
            ))

    # Symlinks must stay inside the skill and must not point at sensitive paths.
    # Read only the link text; never open the target.
    for path in walk_entries(root):
        if not path.is_symlink():
            continue
        relative = path.relative_to(root)
        try:
            os.readlink(path)
        except OSError:
            issues.append(issue(
                "warning", "symlink_unreadable",
                "symlink target cannot be read; replace it with an in-skill file", relative,
            ))
            continue
        try:
            resolved = path.resolve(strict=False)
            link_valid = path.exists()
        except (OSError, RuntimeError):
            resolved = None
            link_valid = False
        if not link_valid or resolved is None or not path_inside(resolved, root_resolved):
            issues.append(issue(
                "error", "symlink_outside",
                "symlink points outside the skill or is broken; replace it with an in-skill path",
                relative,
            ))
        elif is_sensitive(resolved):
            issues.append(issue(
                "error", "symlink_sensitive",
                "symlink points at a sensitive path; remove it or use an approved secret store",
                relative,
            ))
        else:
            issues.append(issue(
                "info", "symlink_internal",
                "symlink points inside the skill; verify it is intentional", relative,
            ))

    for path in text_files(root):
        content = read_text(path)
        relative = path.relative_to(root)
        for match in HOST_PATH_RE.finditer(content):
            issues.append(issue(
                "error" if publish else "info", "path_absolute_host",
                "content contains a host-specific absolute path",
                relative, line_number(content, match.start()),
            ))
        if secrets:
            for pattern_name, severity, pattern in SECRET_PATTERNS:
                for match in pattern.finditer(content):
                    value = match.group(1) if match.groups() else match.group(0)
                    if pattern_name in (
                        "mysql_dsn", "tos_credential", "cloud_key", "literal_secret"
                    ) and placeholder(value):
                        continue
                    issues.append(issue(
                        severity, "secret_pattern",
                        "possible %s; value not printed" % pattern_name,
                        relative, line_number(content, match.start()), pattern=pattern_name,
                    ))

    # Script syntax. Compile Python in memory; use bash -n for shell.
    for path in walk_files(root):
        relative = path.relative_to(root)
        if path.suffix == ".py":
            content = read_text(path)
            try:
                compile(content, str(path), "exec")
            except SyntaxError as exc:
                issues.append(issue(
                    "error", "script_syntax",
                    "Python syntax error: %s" % exc.msg, relative, exc.lineno,
                ))
        elif path.suffix in (".sh", ".bash", ".zsh"):
            bash = shutil.which("bash")
            if not bash:
                issues.append(issue(
                    "info", "script_check_unavailable",
                    "bash not found; shell syntax not checked", relative,
                ))
                continue
            try:
                result = subprocess.run(
                    [bash, "-n", str(path)],
                    capture_output=True, text=True, timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                issues.append(issue(
                    "warning", "script_check_failed",
                    "shell syntax check failed to run: %s" % exc, relative,
                ))
                continue
            if result.returncode != 0:
                detail = result.stderr or result.stdout or ""
                match = re.search(r"line (\d+)", detail)
                line = int(match.group(1)) if match else None
                # Never echo stderr: bash may print the offending line, which can
                # contain a credential. Report only a generic message and line.
                issues.append(issue(
                    "error", "script_syntax",
                    "shell syntax error; offending content not printed",
                    relative, line,
                ))

    # Optional staleness: only explicit last_validated metadata, never guessed dates.
    if stale_days and stale_days > 0:
        cutoff = datetime.date.today() - datetime.timedelta(days=stale_days)
        candidates = [(skill_md, text)]
        for path in markdown_files:
            if path != skill_md:
                candidates.append((path, read_text(path)))
        for path, content in candidates:
            for match in STALE_RE.finditer(content):
                try:
                    observed = datetime.date.fromisoformat(match.group(1))
                except ValueError:
                    continue
                if observed < cutoff:
                    issues.append(issue(
                        "warning", "stale_metadata",
                        "last_validated %s is older than %d days" % (observed, stale_days),
                        path.relative_to(root), line_number(content, match.start()),
                    ))

    return issues


def check(library, names, all_skills=False, stale_days=90, strict=False, secrets=True, publish=False):
    library = absolute(library)
    if all_skills and names:
        raise ValueError("Choose explicit names or --all, not both")
    if all_skills:
        names = [p.name for p in entries(library) if metadata(p)["has_skill_md"]]
    elif not names:
        raise ValueError("Select at least one skill, or use --all")
    names = list(dict.fromkeys(names))
    skills = []
    errors = warnings = info = 0
    for name in names:
        try:
            valid_name(name)
        except ValueError as exc:
            skills.append({
                "name": name, "path": str(library / name),
                "source_kind": "invalid", "issues": [issue("error", "name_invalid", str(exc))],
            })
            errors += 1
            continue
        entry = library / name
        skill = {
            "name": name,
            "path": str(entry),
            "source_kind": source_kind(entry) if os.path.lexists(entry) else "missing",
            "issues": [],
        }
        if not os.path.lexists(entry):
            skill["issues"].append(issue("error", "skill_missing", "library entry does not exist"))
        else:
            try:
                root = entry.resolve(strict=True)
            except (OSError, RuntimeError):
                skill["issues"].append(issue("error", "broken_link", "library entry is a broken link"))
                root = None
            if root is not None:
                if not root.is_dir():
                    skill["issues"].append(issue("error", "skill_not_directory", "skill is not a directory"))
                else:
                    skill["issues"].extend(check_skill(
                        root, stale_days, secrets, name, entry.is_symlink(), publish
                    ))
        for item in skill["issues"]:
            if item["severity"] == "error":
                errors += 1
            elif item["severity"] == "warning":
                warnings += 1
            else:
                info += 1
        skills.append(skill)
    ok = errors == 0 and (not strict or warnings == 0)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now(),
        "library": str(library),
        "ok": ok,
        "strict": strict,
        "publish": publish,
        "counts": {
            "skills": len(skills),
            "errors": errors,
            "warnings": warnings,
            "info": info,
        },
        "skills": skills,
    }


def check_text(report, verbose=False):
    lines = [
        "skills-manager check: %d skills, %d errors, %d warnings, %d info"
        % (
            report["counts"]["skills"], report["counts"]["errors"],
            report["counts"]["warnings"], report["counts"]["info"],
        )
    ]
    shown = 0
    for skill in report["skills"]:
        visible = [
            item for item in skill["issues"]
            if verbose or item["severity"] != "info"
        ]
        if not visible:
            continue
        shown += 1
        has_error = any(item["severity"] == "error" for item in skill["issues"])
        has_warning = any(item["severity"] == "warning" for item in skill["issues"])
        label = "FAIL" if has_error or (report.get("strict") and has_warning) else (
            "WARN" if has_warning else "INFO"
        )
        lines.append("%s %s" % (label, skill["name"]))
        for item in visible:
            location = ""
            if item.get("file"):
                location = item["file"]
                if item.get("line"):
                    location += ":%s" % item["line"]
            lines.append(
                "  %-5s %-22s %-24s %s"
                % (item["severity"].upper(), item["code"], location, item["message"])
            )
    if shown == 0:
        lines.append("OK: no errors or warnings")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("inventory", help="Read directory metadata and report installation state")
    listing.add_argument("--strict", action="store_true", help="Exit nonzero when conflicts are present")
    linking = commands.add_parser("sync", help="Preview missing links; --apply creates them")
    checking = commands.add_parser("check", help="Read-only validation of skill content")
    for command in (listing, linking, checking):
        command.add_argument("--library", default=str(default_library()), help="Canonical source library (default: ~/skills-manager)")
    for command in (listing, linking):
        command.add_argument("--agent-root", action="append", dest="roots")
    linking.add_argument("names", nargs="*")
    linking.add_argument("--all", action="store_true", dest="all_skills")
    linking.add_argument("--apply", action="store_true")
    checking.add_argument("names", nargs="*")
    checking.add_argument("--all", action="store_true", dest="all_skills")
    checking.add_argument("--strict", action="store_true", help="Treat warnings as failure")
    checking.add_argument("--stale-days", type=int, default=90, help="Flag explicit last_validated older than this (0 disables)")
    checking.add_argument("--no-secrets", action="store_true", dest="no_secrets")
    checking.add_argument("--publish", action="store_true", help="Treat host-specific paths and outside links as errors")
    checking.add_argument("--format", choices=("json", "text"), default="json")
    checking.add_argument("--verbose", action="store_true", help="Include info findings in text output")
    args = parser.parse_args(argv)
    try:
        roots = default_roots() if getattr(args, "roots", None) is None else args.roots
        if args.command == "inventory":
            report = inventory(args.library, roots)
        elif args.command == "sync":
            report = sync(args.library, roots, args.names, args.all_skills, args.apply)
        else:
            report = check(
                args.library, args.names, args.all_skills, args.stale_days,
                args.strict, not args.no_secrets, args.publish,
            )
        if args.command == "check" and args.format == "text":
            print(check_text(report, getattr(args, "verbose", False)))
        else:
            print(json.dumps(report, indent=2))
        if args.command == "inventory" and not getattr(args, "strict", False):
            return 0
        return 0 if report.get("ok", True) else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
