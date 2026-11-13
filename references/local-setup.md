# Central skill library for the current user

This installation uses `~/skills-manager` as the canonical source library. This
supersedes the earlier setup that kept sources in separate agent folders. Store
created and downloaded personal skills there, apply updates to their canonical
sources, and deploy per-skill links into selected agent roots. Set any
installer's destination explicitly to the central library.

| Purpose | Directory |
| --- | --- |
| Canonical sources | `~/skills-manager` |
| Codex discovery | `~/.codex/skills` |
| Shared agent discovery | `~/.agents/skills` |
| Claude discovery | `~/.claude/skills` |
| Cursor discovery | `~/.cursor/skills` |

Honor a different `CODEX_HOME` for the Codex discovery root. The manager's source
is `~/skills-manager/skills-manager`; its old Codex path remains a link.

## Inventory and synchronization

The helper defaults to `~/skills-manager`, independently of `CODEX_HOME`.
Use `--library` for a selected variant or another user-selected library.
Missing mounts are informational; centralization does not deploy every skill
into every agent. Include explicit `--agent-root` options for Cursor or another
agent outside the helper's default shared/Codex/Claude roots.

```bash
python3 ~/skills-manager/skills-manager/scripts/skills_manager.py inventory
```

Differing same-name sources are preserved in
`~/skills-manager/.variants/<context>/<skill-name>`. Inventory a context with
`--library ~/skills-manager/.variants/<context>`. Old discovery links point to
their own versions; update the version used by the requested agent.

Content validation is separate from link synchronization:

```bash
python3 ~/skills-manager/skills-manager/scripts/skills_manager.py check --all --format text
```

`check` reads skill content offline; it does not create or change discovery links.

The local search index is separate from the library:

```bash
python3 ~/skills-manager/skills-manager/scripts/skill_catalog.py catalog
python3 ~/skills-manager/skills-manager/scripts/skill_catalog.py search "..." --format text
```

It stores `~/.arvey-config/skills-manager/catalog.json` (0600, local-only). Rebuild
it after adding or renaming a skill; never publish it as a document.

For synchronization, use the central library or selected variant context as
`--library` and only the requested destination directories as `--agent-root`.
Preview first and apply when the request authorizes the resulting links. Managing
existing skills does not itself request deployment into additional agents.
For example, a request to make `baoyu-design` available in the shared folder uses:

```bash
python3 ~/skills-manager/skills-manager/scripts/skills_manager.py sync baoyu-design \
  --agent-root ~/.agents/skills
```

Preserve `~/.codex/skills/.system`, plugin caches,
`~/.agents/.skill-lock.json`, nested skill resources and existing local
edits. Follow the lifecycle reference for selected installs and updates; choose
the canonical source and selected discovery links. Follow `consolidation.md`
for broad scans and migrations. Reports and backups belong under the library's
hidden `.reports` and `.backups` directories. Preserve the selected policy for
project authoring sources recorded in the migration report.

Keep reports, backups and credentials out of published skill repositories. When
an agent setup request authorizes updating its instruction file, record the
canonical source and per-skill discovery link policy there. Preserve unrelated
instructions and the selected project-source policy.

## Installation provenance

- Source: https://github.com/ArveyKao/skills-manager
- Reviewed and integrated upstream revision: `510faa27a9ab0b38936526f0228c00fdc1a0dca4` (2026-11-11)
- Original installation: `b1a2ffb773cf12883cbb2a30225a694afdc5c4c3` (2026-10-08)
- Local adaptation: central-library defaults, local workflow documentation,
  read-only content validation, and CLI regression tests.
- The license and helper's inventory/synchronization behavior are preserved.

When updating, preserve this local adaptation and compare safe skill files with
the latest integrated revision; the installed copy is not a Git checkout.
