# Central skill library

The default source library is `~/skills-manager`. Honor a user-selected library
path and preserve that choice across installations and updates. Created and
downloaded personal skills belong in `<library>/<skill-name>`; update their
canonical sources there and deploy per-skill symlinks into selected agent roots.
Set any installer's destination explicitly to the source library.

| Purpose | Default directory |
| --- | --- |
| Canonical sources | `~/skills-manager` |
| Manager source | `~/skills-manager/skills-manager` |
| Codex discovery | `$CODEX_HOME/skills`, or `~/.codex/skills` |
| Shared agent discovery | `~/.agents/skills` |
| Claude discovery | `~/.claude/skills` |
| Cursor discovery | `~/.cursor/skills` |

`CODEX_HOME` selects only the Codex discovery root. The helper's source library
default remains `~/skills-manager`; use `--library` to override it. Include
explicit `--agent-root` options for Cursor or another agent outside the helper's
default shared/Codex/Claude roots.

```bash
python3 ~/skills-manager/skills-manager/scripts/skills_manager.py inventory
python3 ~/skills-manager/skills-manager/scripts/skills_manager.py sync example-skill \
  --agent-root ~/.codex/skills --agent-root ~/.cursor/skills
```

Missing mounts are informational; centralization does not deploy every skill
into every agent. Preview synchronization first and apply when the user's
request authorizes the selected links.

Differing same-name sources may be preserved under
`<library>/.variants/<context>/<skill-name>`. Inventory a context with
`--library <library>/.variants/<context>`. Existing discovery links must retain
their original names and point to their own versions. Update the version used
by the requested agent, rather than replacing another variant by name alone.

For explicitly authorized project-source moves, `.projects/<project>` can
preserve relative source structure and central aliases can expose skill names.
Prepare the required shared-dependency links before moving sources. Run existing
workflows at their original compatibility paths when access hooks match those
paths literally. See [consolidation.md](consolidation.md) for discovery, backup,
migration and verification.

Keep timestamped backups and host-specific reports in hidden `.backups` and
`.reports` directories. Preserve managed `.system` directories, plugin caches,
application resources, lock files, local edits and project-specific instructions.
Do not publish a user's reports, backups or credentials with the manager.

To make this layout persistent for an agent, add a narrowly scoped personal-skill
policy to its supported instruction file when the setup request authorizes it:
new personal sources and updates go into the canonical library, and agent skill
folders hold per-skill links. Preserve unrelated instructions and the user's
chosen project-source policy.
