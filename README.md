# skills-manager

A reusable agent skill for maintaining a shared personal skill library. It uses
the existing `~/arveyskills` architecture, with per-skill symlinks under
`~/.agents/skills`, `~/.codex/skills`, and `~/.claude/skills`.

The repository root is the installable skill directory. Read [SKILL.md](SKILL.md)
for the agent workflow: inventory, installation, synchronization, updates, link
repair, and publication. Vendor-managed skills and plugin caches stay in place.

## Install

Clone into a new canonical directory, then preview the links:

```bash
git clone https://github.com/ArveyKao/skills-manager.git ~/arveyskills/skills-manager
cd ~/arveyskills/skills-manager
python3 scripts/skills_manager.py sync skills-manager
python3 scripts/skills_manager.py sync skills-manager --apply
```

Existing conflicting paths are preserved. The helper requires Python 3.9+ and
no additional packages. `CODEX_HOME`, when set, selects the Codex home. These
directory defaults reflect this library's layout; agent discovery still depends
on the installed application and its configuration.

## Use

Ask your agent:

> Use skills-manager to check my skill library and synchronize missing links.

Or run the helper directly:

```bash
python3 scripts/skills_manager.py inventory
python3 scripts/skills_manager.py sync huashu-design baoyu-design
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

Git installation, updates, repair and publishing are agent-guided workflows, not
background services or automatic downloads performed by the helper.

## Verify

```bash
python3 -m unittest discover -s tests -v
```

Tests use temporary libraries and agent directories. They cover synchronization,
idempotence, preservation of conflicts and broken links, partial failure, invalid
names, and inventory without file-content reads.

Licensed under [MIT](LICENSE).
