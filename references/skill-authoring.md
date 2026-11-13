# Personal skill authoring standard

Apply this standard to new and substantially rewritten personal skills. For an
overlap review, compare nearby skills by the requests they handle, their
procedures, and the evidence they produce. Prefer extending the existing owner
of a capability. Before merging, renaming, or retiring a skill, check its
consumers and discovery links. Preserve local variants and compatibility paths
as described in [the lifecycle guide](lifecycle.md).

When documenting a procedure, prefer a supported MCP tool, CLI or script that
can complete the step and return verifiable evidence. Use browser or UI
interaction only when those cannot complete the authorized action, or when the
result needs visual acceptance. Name the chosen tool where it affects execution,
and describe any UI fallback at the step that needs it.

## Strategy and tactics

- **Strategy skills** own the objective and complete workflow: scope, required
  and conditional stages, dependencies, decision points, and evidence needed to
  advance or finish. Give each end-to-end workflow a clear entry point. Link
  to the tactical skill at the stage that needs it.
- **Tactical skills** own a focused procedure. State when to use it, what inputs
  it needs, how to execute and verify it, and what evidence or blocker to return.
  Accept inputs from a strategy skill or resolve them from the current request
  when invoked directly. A tactic should not need to load its parent workflow.

Keep one owner for shared instructions. A strategy should describe why and when
to run a tactic without copying its procedure. Keep always-needed constraints in
`SKILL.md` and link to details where they become relevant. Load only the current
stage's skill and references. A focused task can use a tactical skill directly;
there is no need to create a strategy skill for every tactic. If a required
dependency is unavailable, mark the affected stage blocked.

For work that spans sessions or needs a handoff, initialize or reuse a project
record with stable stage IDs, dependencies, status, and acceptance criteria.
Pass only the relevant scope, inputs, prior evidence, and constraints to the
next tactic. Record the result before advancing. After a context reset or
handoff, reopen the record and resume from the next eligible stage. Before
closing the workflow, account for every stage: verify required stages and
record why any conditional stage did not apply.

For example, a cloud migration strategy tracks discovery, target foundation,
data synchronization, service deployment, cutover, and observation. A data sync
skill can also run on its own. After a context reset, the strategy checks the
record for reconciliation and restore evidence before treating data sync as
complete or advancing to a dependent cutover.

## Configuration, secrets, and document destinations

For project configuration and secret files the agent manages locally, use the
established project identifier under `~/arvey-config/<project>/`. Keep ordinary
configuration in `files/` and secret files in a separate, access-restricted
`secrets/` directory. Honor any required secret store; reference its entries by
ID. Keep secret values out of skill sources, Git, project documents, and logs.

Before storing project documents for the first time, ask the user where they
should live. Offer `~/arvey-config/<project>/documents/` as the default and wait
for the user's choice. The user can choose Google Docs, Lark Docs, Notion, or
another local path. If the user has already chosen a destination, reuse it.
Create or update the requested files, pages, tables, or other artifacts within
that location using its native capabilities.
If access or a required capability is missing, report the gap before switching
destinations. Keep configuration and secret files separate from shared documents.

## Project document index

Maintain one index file at `~/arvey-config/<project>/document-index.md`, even
when the documents live elsewhere. Record the user's chosen destination at
the top so future agents can reuse it. Give each project document one entry with
its title, category, path or link, and a short description. Use the project's
existing categories if available. Update the index when a document is created,
renamed, moved, reclassified, archived, or removed. Consult the index before
searching folders or document services.

## Records for ongoing work

Use the destination and index rules whenever a skill writes project documents.
Introduce a standing project record only when the work needs to survive an
interruption, span sessions, track dependent stages, or pass between agents or
people. A one-off task may still produce a requested document or table; it
does not need a standing record just because it creates an artifact.

Reuse the project's authoritative document, table, or existing record. Update
it as decisions, configuration references, verification evidence, and stage
status change. Record what is still pending and the next step. Resolve
contradictions at their source and derive any summary from the current record
instead of maintaining a second copy of the project state.

## Retrieval metadata

A skill's `description` is the always-visible routing summary; `whenToUse` and
`aliases` improve retrieval without enlarging the session catalog:

```yaml
---
name: deploy-gms-frontend
description: Deploy a static frontend through deploy-gms and sync its Ingress.
whenToUse: Use when a GMS static site needs a new environment or domain.
aliases: gms-web, static-site, frontend-deploy
---
```

- Keep `description` stable, specific and trigger-rich; it is cached context.
- Put task-shaped phrases in `whenToUse`; the local catalog search exposes it.
- Put user vocabulary, acronyms and Chinese/English variants in `aliases`
  (comma-separated or a single-line list).
- Do not put secrets or project-specific values in any of these fields.

Run `skill_catalog.py catalog` after changing them, then `catalog --check` before
publishing.

## Validate before publishing

Run the manager's read-only content check before publishing or after a
substantial rewrite:

```bash
python3 scripts/skills_manager.py check <skill-name> --format text
python3 scripts/skills_manager.py check <skill-name> --publish
python3 scripts/skills_manager.py check --all
```

It validates frontmatter name/description, relative links, symlinks, file
permissions, Python and shell syntax, high-confidence secret patterns and
explicit `last_validated` dates. It is a structural check, not a workflow test:
still run a representative request and the skill's own tests. Use
`check --publish` before publishing; it turns host-specific paths and links that
resolve outside the skill into errors. Before finishing, confirm:

- [ ] `name` matches the directory and the description names specific triggers.
- [ ] Relative links resolve inside the skill; host-specific absolute paths are absent or justified.
- [ ] Symlinks stay inside the skill and do not point at credential stores.
- [ ] Referenced scripts compile or pass their tests; no secrets are included.
- [ ] One owner exists for the capability; views are not competing strategies.
- [ ] Document-producing skills record the chosen destination and index.
- [ ] Environment-specific facts carry `last_validated` and are refreshed.
- [ ] An interrupted strategy resumes from the record without skipping a stage.

## Common failure modes

| Failure | Symptom | Correction |
| --- | --- | --- |
| Two owners for one capability | Two coordinators, plans or ledgers drift | Keep one strategy owner; make the other a compatibility entry point |
| A view competes with the strategy | A plan template or progress table becomes a second plan | Keep plan/progress as derived views; link to the owner |
| Declaration treated as live state | A chart, wiki or repository says the service exists | Observe the runtime; tag `Observed`, `Inferred` or `Unknown` |
| Host-specific paths and broken links | The skill works only on the author's machine | Use relative links and run the content check |
| Stale case studies or learnings | Old versions and prices are replayed as current | Date the facts, separate historical evidence, refresh per use |
| "Done" document trusted over evidence | A report says complete while live checks disagree | Reopen the record and verify the actual acceptance evidence |
| Overlapping triggers | Several skills claim the same request | Compare requests, procedures and evidence; extend one owner |

## Cleanup and review

Use a task-specific temporary directory for scratch work. Once the result is
verified, remove the temporary files and directories created by the task that
are no longer needed. Retain requested outputs and anything needed for
verification, resumption, or recovery; leave pre-existing files alone.

Before finishing an authoring change, check whether a representative request
routes to the right owner, a tactic can be invoked directly, and an interrupted
strategy can resume without skipping a required stage. For document-producing
skills, check the selected destination, document index, and whether a standing
record is needed.
