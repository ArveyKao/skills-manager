#!/usr/bin/env python3
"""Build a local skill catalog and search it by user intent.

The catalog is local-only operational metadata: it stores summaries, not skill
bodies or secrets. It is an index for retrieval, not a second source of truth;
rebuild it from the library and use `skill({name})` to load the real body.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata

try:
    import skills_manager as sm
except ImportError:  # Direct import from tests or an unusual cwd.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import skills_manager as sm


CATALOG_SCHEMA_VERSION = 1
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
CATALOG_FILE = "catalog.json"

# A small, local synonym layer. Keep it generic; project-specific aliases
# belong in each skill's frontmatter so the catalog stays the single index.
ALIASES = {
    "k8s": "kubernetes",
    "kubernetes": "k8s",
    "feishu": "lark",
    "lark": "feishu",
    "volcengine": "volcano",
    "volcano": "volcengine",
    "aliyun": "alibaba",
    "alibaba": "aliyun",
    "dns": "domain",
    "domain": "dns",
    "cert": "certificate",
    "certificate": "cert",
    "migrate": "migration",
    "migration": "migrate",
    "deploy": "deployment",
    "deployment": "deploy",
    "bill": "billing",
    "billing": "bill",
    "configure": "configuration",
    "configuration": "configure",
    "monitor": "monitoring",
    "monitoring": "monitor",
}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "i", "in", "is", "it", "of", "on", "or", "that", "the", "to", "with",
    "please", "can", "you", "we", "our", "this", "these", "those",
}

WEIGHTS = {
    "name": 5.0,
    "aliases": 4.0,
    "when_to_use": 3.0,
    "tags": 3.0,
    "description": 2.0,
}


def default_catalog_path():
    return Path.home() / ".arvey-config" / "skills-manager" / CATALOG_FILE


def absolute(value):
    return Path(os.path.abspath(Path(value).expanduser()))


def normalize(value):
    return unicodedata.normalize("NFKC", value or "").casefold()


def split_list(value):
    """Accept `[a, b]`, `a, b`, or a scalar string."""
    value = (value or "").strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [item.strip().strip("'\"") for item in value.split(",") if item.strip().strip("'\"")]


def frontmatter_value(frontmatter, *keys):
    for key in keys:
        value = frontmatter.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def token_set(text):
    text = normalize(text)
    words = {
        word for word in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text)
        if word not in STOPWORDS
    }
    for word in list(words):
        words.update(part for part in re.split(r"[-_]", word) if part)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    words.update("".join(cjk[index:index + 2]) for index in range(len(cjk) - 1))
    return words


def expand(tokens):
    result = set(tokens)
    for token in tokens:
        other = ALIASES.get(token)
        if other:
            result.add(other)
    return result


def skill_record(path):
    skill_file = path / "SKILL.md"
    text = sm.read_text(skill_file)
    status, frontmatter = sm.parse_frontmatter(text)
    name = frontmatter_value(frontmatter, "name") or path.name
    description = frontmatter_value(frontmatter, "description")
    when_to_use = frontmatter_value(
        frontmatter, "whenToUse", "when_to_use", "when-to-use"
    )
    aliases = split_list(frontmatter_value(frontmatter, "aliases", "alias"))
    tags = split_list(frontmatter_value(frontmatter, "tags", "tag"))
    disable_model = frontmatter_value(
        frontmatter, "disable-model-invocation", "disable_model_invocation"
    ).casefold() in ("true", "yes", "1")
    disable_user = frontmatter_value(
        frontmatter, "user-invocable", "user_invocable"
    ).casefold() in ("false", "no", "0")
    record = {
        "name": name,
        "description": description,
        "when_to_use": when_to_use,
        "aliases": aliases,
        "tags": tags,
        "source_kind": sm.source_kind(path),
        "model_invocable": not disable_model,
        "user_invocable": not disable_user,
        "last_validated": frontmatter_value(frontmatter, "last_validated"),
        "content_hash": hashlib.sha256(skill_file.read_bytes()).hexdigest(),
        "path": str(path),
        "frontmatter_status": status,
    }
    return record


def catalog_revision(skills):
    canonical = [
        {
            key: skill[key]
            for key in (
                "name", "description", "when_to_use", "aliases", "tags",
                "source_kind", "model_invocable", "user_invocable",
                "last_validated", "content_hash",
            )
        }
        for skill in sorted(skills, key=lambda item: item["name"])
    ]
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def build_catalog(library):
    library = absolute(library)
    if not library.is_dir():
        raise ValueError("Library must be an existing directory")
    skills = {}
    skipped = 0
    duplicates = 0
    for path in sm.entries(library):
        if not sm.metadata(path)["has_skill_md"]:
            continue
        try:
            record = skill_record(path)
        except OSError:
            skipped += 1
            continue
        if not record["model_invocable"]:
            continue
        previous = skills.get(record["name"])
        if previous is None:
            skills[record["name"]] = record
            continue
        duplicates += 1
        previous_alias = previous.get("source_kind") == "alias"
        current_alias = record.get("source_kind") == "alias"
        if previous_alias and not current_alias:
            skills[record["name"]] = record
        elif previous_alias == current_alias and record.get("path", "") < previous.get("path", ""):
            skills[record["name"]] = record
    skills = sorted(skills.values(), key=lambda item: item["name"])
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "generated_at": sm.now(),
        "library": str(library),
        "revision": catalog_revision(skills),
        "complete": skipped == 0,
        "counts": {
            "skills": len(skills),
            "skipped": skipped,
            "duplicates": duplicates,
            "with_when_to_use": sum(1 for item in skills if item["when_to_use"]),
            "with_aliases": sum(1 for item in skills if item["aliases"]),
        },
        "skills": skills,
    }


def write_catalog(document, path):
    path = absolute(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".catalog-", suffix=".json", dir=str(path.parent)
    )
    try:
        try:
            os.fchmod(descriptor, 0o600)
        except (AttributeError, OSError):
            pass
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def read_catalog(path):
    path = absolute(path)
    if not path.is_file():
        raise ValueError(
            "Catalog not found at %s; run `catalog` first" % path
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Catalog is not valid JSON: %s" % exc) from None
    if not isinstance(document, dict) or document.get("schema_version") != CATALOG_SCHEMA_VERSION:
        raise ValueError("Catalog has an unsupported schema; rebuild it")
    return document


def field_tokens(skill):
    return {
        "name": expand(token_set(skill.get("name", ""))),
        "aliases": expand(token_set(" ".join(skill.get("aliases", [])))),
        "when_to_use": expand(token_set(skill.get("when_to_use", ""))),
        "tags": expand(token_set(" ".join(skill.get("tags", [])))),
        "description": expand(token_set(skill.get("description", ""))),
    }


def score_skill(skill, query_tokens, query_text):
    fields = field_tokens(skill)
    score = 0.0
    matched = set()
    for field, weight in WEIGHTS.items():
        present = query_tokens & fields[field]
        if present:
            matched.update(present)
            score += weight * (len(present) / max(1, len(query_tokens)))
    name = normalize(skill.get("name", ""))
    query = normalize(query_text)
    if query and name == query:
        score += 10.0
        matched.add(query)
    elif query and (name.startswith(query) or query.startswith(name)):
        score += 4.0
        matched.add(query)
    aliases = {normalize(alias) for alias in skill.get("aliases", [])}
    if query and query in aliases:
        score += 3.0
        matched.add(query)
    return score, matched


def confidence(score):
    if score >= 4.0:
        return "high"
    if score >= 1.8:
        return "medium"
    return "low"


def search(catalog_path, query, limit=DEFAULT_LIMIT):
    document = read_catalog(catalog_path)
    query = (query or "").strip()
    if not query:
        raise ValueError("Search query must not be empty")
    limit = max(1, min(int(limit), MAX_LIMIT))
    query_tokens = expand(token_set(query))
    if not query_tokens:
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "query": query,
            "revision": document.get("revision"),
            "total": 0,
            "complete": document.get("complete", True),
            "no_match": True,
            "reason": "no_searchable_tokens",
            "candidates": [],
        }
    ranked = []
    for skill in document.get("skills", []):
        score, matched = score_skill(skill, query_tokens, query)
        if score <= 0:
            continue
        ranked.append((score, skill, matched))
    ranked.sort(key=lambda item: (-item[0], item[1].get("name", "")))
    candidates = []
    for score, skill, matched in ranked[:limit]:
        item = {
            "name": skill.get("name"),
            "description": (skill.get("description") or "")[:180],
            "confidence": confidence(score),
            "matched": sorted(matched)[:5],
        }
        if skill.get("when_to_use"):
            item["when_to_use"] = skill["when_to_use"][:180]
        candidates.append(item)
    no_match = not ranked or ranked[0][0] < 1.0
    if no_match:
        candidates = []
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "query": query,
        "revision": document.get("revision"),
        "total": len(ranked),
        "complete": document.get("complete", True),
        "no_match": no_match,
        "reason": "no_confident_match" if no_match else None,
        "candidates": candidates,
    }


def search_text(report):
    if report.get("no_match"):
        return "skills-manager search: no confident match for %r" % report["query"]
    lines = [
        "skills-manager search: %d candidate(s) for %r"
        % (len(report["candidates"]), report["query"])
    ]
    for index, item in enumerate(report["candidates"], 1):
        lines.append(
            "%d. %s  [%s]  matched: %s"
            % (index, item["name"], item["confidence"], ", ".join(item["matched"]))
        )
        if item.get("description"):
            lines.append("   %s" % item["description"])
        if item.get("when_to_use"):
            lines.append("   when: %s" % item["when_to_use"])
    return "\n".join(lines)


def catalog_text(report, path, dry_run=False):
    return "\n".join([
        "skills-manager catalog: %d skill(s), revision %s"
        % (report["counts"]["skills"], report["revision"]),
        "with whenToUse: %d; with aliases: %d"
        % (report["counts"]["with_when_to_use"], report["counts"]["with_aliases"]),
        ("not written (dry run)" if dry_run else "written to %s" % path),
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("catalog", help="Build the local skill catalog")
    build.add_argument("--library", default=str(sm.default_library()))
    build.add_argument("--catalog", default=str(default_catalog_path()))
    mode = build.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print without writing")
    mode.add_argument("--check", action="store_true", help="Check whether the catalog is current")
    build.add_argument("--format", choices=("json", "text"), default="json")

    find = commands.add_parser("search", help="Search the local skill catalog by intent")
    find.add_argument("query")
    find.add_argument("--catalog", default=str(default_catalog_path()))
    find.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    find.add_argument("--format", choices=("json", "text"), default="json")

    args = parser.parse_args(argv)
    try:
        if args.command == "catalog":
            document = build_catalog(args.library)
            if args.check:
                try:
                    existing = read_catalog(args.catalog)
                    complete = bool(document.get("complete", True))
                    current = existing.get("revision") == document["revision"] and complete
                    result = {
                        "ok": current,
                        "stale": not current,
                        "complete": complete,
                        "catalog": str(absolute(args.catalog)),
                        "expected_revision": document["revision"],
                        "catalog_revision": existing.get("revision"),
                        "counts": document["counts"],
                    }
                except ValueError as exc:
                    result = {
                        "ok": False,
                        "stale": True,
                        "catalog": str(absolute(args.catalog)),
                        "expected_revision": document["revision"],
                        "error": str(exc),
                    }
                if args.format == "text":
                    print("skills-manager catalog: %s" % ("current" if result["ok"] else "stale"))
                else:
                    print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0 if result["ok"] else 1
            if args.dry_run:
                if args.format == "text":
                    print(catalog_text(document, args.catalog, dry_run=True))
                else:
                    print(json.dumps(document, ensure_ascii=False, indent=2))
                return 0
            path = write_catalog(document, args.catalog)
            if args.format == "text":
                print(catalog_text(document, path))
            else:
                print(json.dumps({
                    "schema_version": CATALOG_SCHEMA_VERSION,
                    "catalog": str(path),
                    "revision": document["revision"],
                    "counts": document["counts"],
                }, ensure_ascii=False, indent=2))
            return 0
        report = search(args.catalog, args.query, args.limit)
        if args.format == "text":
            print(search_text(report))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if not report.get("no_match") else 1
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
