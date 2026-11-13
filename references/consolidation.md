# Discover and consolidate personal skills

For machine-wide discovery, inventory known agent roots and then search
accessible real roots in the user's home, shared user directories, local
application/support directories, package locations and mounted data volumes.
Use bounded `rg --files --hidden --no-ignore -g SKILL.md` filename searches.
Exclude secret stores, `.env*`, keys, `.git` internals and dependencies from
traversal. Do not follow filesystem aliases or directory symlinks blindly.
Record inaccessible locations rather than claiming they were scanned.

Classify candidates before reading skill content. Personal installations,
downloads and standalone authored skills are candidates. Vendor-managed
`.system`, plugins, application/package resources, templates, tests, archives
and temporary review copies remain managed by their owners. A nested bundled
skill moves with its parent. Standalone skill repositories can be moved intact;
skills inside development repositories follow the user's selected repository
policy to preserve Git authoring sources or explicitly move them with links.

Record exact old paths, intended canonical paths and safe fingerprints. Back up
selected originals before moving them. Equivalent copies may share a canonical
target after preserving originals. Differing same-name versions retain separate
targets under `~/skills-manager/.variants/<context>/<skill-name>`. Keep file
permissions and symlink targets; relative links must retain their meaning after
relocation. Keep unresolved candidates pending rather than create broken links.

Replace only selected directory entries with links to their canonical sources.
Preserve original discovery names and compatibility paths. Never replace an
entire agent's `skills` directory. Verify each old path resolves to the preserved
content and save a manifest with sources, targets, variants, backups, exclusions,
completed actions and unresolved cases. Restore the original path if a move/link
step fails. Retain backups after ordinary consolidation.

The bundled `scripts/consolidate_skills.py` accepts an explicit JSON manifest
with `library`, `entries` (`source` and `target` paths) and optional `report_path`.
It previews by default; `--apply` backs up, verifies, moves and links the selected
sources. It blocks conflicts, overlapping sources, Git worktree metadata and
external relative symlinks. For a package without a root SKILL.md, explicitly list
its relative child skill directories in the entry's `skills` field.

```bash
python3 ~/skills-manager/skills-manager/scripts/consolidate_skills.py manifest.json
python3 ~/skills-manager/skills-manager/scripts/consolidate_skills.py manifest.json --apply
```

The user selected moving project skill folders with original-path symlinks.
Place those sources under `.projects/<project>/<original-relative-path>` and
expose their skill names through central aliases. Before applying the move, prepare needed ancestor
relationships with absolute links to unmoved shared helpers and configuration
files, using metadata only for credential-bearing files. Keep access-gate hooks
at their original paths and retain original command paths where their matchers
depend on them. Update canonical sources centrally; changing an execution path
that is checked by a hook is a separate compatibility change. Dependency mirrors
are prepared by the agent; the consolidation helper only applies the explicit
source/target moves. Its exclusive rename requires macOS or Linux with
`renameat2`; unsupported platforms fail safely without replacing originals.

For future creation, downloads and updates, use the canonical library first and
then synchronize selected agent links. This is an agent workflow; the skill
does not run a background scanner or intercept unrelated installers.
