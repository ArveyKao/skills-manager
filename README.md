# skills-manager

A reusable agent skill for maintaining a shared personal skill library. It uses
the central `~/skills-manager` library, with per-skill symlinks under
`~/.agents/skills`, `~/.codex/skills`, and `~/.claude/skills`.

The repository root is the installable skill directory. Read [SKILL.md](SKILL.md)
for the agent workflow: machine-wide discovery, consolidation, installation,
synchronization, updates, link repair, and publication. Vendor-managed skills
and plugin caches stay in place.

## Install

Clone into a new canonical directory, then preview the links:

```bash
git clone https://github.com/ArveyKao/skills-manager.git ~/skills-manager/skills-manager
cd ~/skills-manager/skills-manager
python3 scripts/skills_manager.py sync skills-manager
python3 scripts/skills_manager.py sync skills-manager --apply
```

Existing conflicting paths are preserved. The helper requires Python 3.9+ and
no additional packages. The source library defaults to `~/skills-manager`;
`--library` selects another source library. `CODEX_HOME`, when set, selects only
the Codex discovery home. New skills and updates belong in the central library.
These directory defaults reflect this library's layout; agent discovery still
depends on the installed application and its configuration.

## Use

Ask your agent:

> Use skills-manager to check my skill library and synchronize missing links.

Or run the helper directly:

```bash
python3 scripts/skills_manager.py inventory
python3 scripts/skills_manager.py sync example-skill
python3 scripts/skills_manager.py sync --all --apply
python3 scripts/skills_manager.py inventory --library /path/to/library \
  --agent-root /path/to/agent/skills
```

- `inventory` reads filesystem metadata and prints JSON; it does not read skill
  contents, credentials, Git configuration, or plugin manifests.
- `sync` previews by default. `--apply` creates missing symlinks, with no
  overwrites or deletion. Explicit names or `--all` are required.
- `--all` selects only immediate, non-hidden library entries with a `SKILL.md`.
  Supporting repositories without that file are skipped.
- Repeated `--agent-root` options replace all default roots.
- Any detected conflict prevents the plan from applying. If an I/O failure
  occurs during creation, earlier links can remain; JSON records partial results.

## Consolidate existing sources

Ask your agent to discover personal skills across accessible machine locations
and consolidate selected sources into the central library. It preserves managed
resources, project policy, differing versions and original discovery paths.

The consolidation helper consumes an explicit manifest and previews by default:

```json
{
  "library": "/path/to/skills-manager",
  "entries": [{
    "source": "/path/to/agent/skills/example-skill",
    "target": "/path/to/skills-manager/example-skill"
  }],
  "report_path": "/path/to/skills-manager/.reports/migration.json"
}
```

```bash
python3 scripts/consolidate_skills.py manifest.json
python3 scripts/consolidate_skills.py manifest.json --apply
```

Apply creates full backups, verifies safe resource fingerprints, moves sources
and links their original locations. Conflicts and overlapping selections block
the plan. A failure preserves backups and reports partial progress or recovery.
Exclusive moves require macOS or Linux with `renameat2`. Prepare shared-dependency
mirrors for project sources separately; see
[the consolidation workflow](references/consolidation.md).

Discovery, Git installation, updates, repair, dependency preparation and
publishing are agent-guided workflows, not background services or automatic
downloads performed by the helpers.

## Verify

```bash
python3 -m unittest discover -s tests -v
```

Tests use temporary libraries and agent directories. They cover synchronization,
idempotence, preservation of conflicts and broken links, partial failure, invalid
names, inventory without file-content reads, consolidation preservation,
conflict rejection and failure recovery.

Licensed under [MIT](LICENSE).
