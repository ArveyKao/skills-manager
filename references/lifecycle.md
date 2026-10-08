# Skill lifecycle in the shared local library

## Install from GitHub or another local source

Confirm the repository/ref and the skill directory. Check the existing library
entry and all intended mounts before copying or cloning. If an entry already
exists, inspect its ownership and state; do not overwrite it to repeat an install.

For a repository-root skill, clone under `~/skills-manager/<name>` to keep its
provenance. Create and download personal skills into that library; set the
installer's destination explicitly, then link selected discovery paths. For a
multi-skill repository, retain the checkout separately
and link only the selected skill subdirectory, or copy that complete subdirectory
into the library and record its source/ref. Do not link the repository root unless
it contains the intended `SKILL.md`. Preserve scripts, references, assets and
licenses. Do not copy a repository's credentials or local build artifacts.

Use the requested ref, not an assumed latest version. Read the skill and inspect
relevant supporting code before executing it. Avoid remote bootstrap commands,
global installs and launching services unless the actual task requires and
authorizes them. Validate the skill's name/description and local resource links.
When the bundled Codex `quick_validate.py` is available, use it; otherwise inspect
the frontmatter and resources directly and state which validation was performed.

Preview and apply the selected symlinks with the helper. On filesystems or agents
without directory-symlink support, explain the limitation and use an explicitly
selected copy-based layout rather than silently creating divergent copies.

## Update a selected skill

Determine the Git ownership boundary first:

```bash
git -C /path/to/skill rev-parse --show-toplevel
git -C /path/to/skill status --short
```

A successful Git command does not prove the skill owns a repository: it may find
the library's `.git` in an ancestor. Do not pull the parent library to update one
copied skill. Do not display `.git/config` or unsanitized remote URLs.

For a standalone checkout, confirm the intended upstream using a known source
URL or sanitized metadata, inspect the branch and local changes, fetch the exact
intended ref, and review the relevant diff before updating. Fast-forward a clean
checkout only when its current branch matches the requested update. Preserve
dirty, divergent and detached checkouts; stage the proposed version separately
and explain the conflict. Do not auto-stash, reset, rebase, switch branches, or
force-push to make an update succeed.

For a copied skill, recover provenance from existing non-sensitive records or
the user. Obtain the selected version in a new temporary directory. Compare only
the skill's safe files, preserve local modifications, and merge the intended
changes into the canonical directory. If provenance is unknown, report that
rather than guessing a repository. Keep the canonical path stable so its agent
links continue to work. Update licenses and supporting resources consistently.

Run applicable validation and helper tests, then inventory the selected mounts.
Report the actual source version; do not claim a copied skill tracks upstream
automatically or that a successful `git fetch` updated its working files.

## Repair links or consolidate duplicates

Use metadata (`lstat`/`readlink`) to distinguish an actual directory from a link,
including a dangling link. Resolve the intended source before changing anything.

- A missing mount can be created by `sync`.
- A correct mount needs no action.
- A dangling or wrong-target link needs a deliberate repair. When that repair
  is authorized and the intended target is known, recheck the exact link, unlink
  only that directory entry, and recreate it. Never recursively delete its target.
- An existing directory may contain unique work. Compare relevant non-sensitive
  files, integrate the desired content, and preserve the old directory at a
  concrete backup location before replacing its mount. If the canonical version
  or disposition of local edits is unclear, ask for that decision.

Preserve project compatibility links, such as a project's legacy `verify` path
pointing to the centralized `chatops-2-verify` skill. Do not rename a skill merely
to make directory names match without checking its consumers and metadata.

## Disable or remove

For removal from an agent, remove only the named discovery link after checking
its current type and target. Retain the canonical source and other agent mounts.
Deleting a canonical skill directory, replacing local edits, removing a plugin,
or publishing a private skill is a separate scope decision; do not infer it from
an inventory, sync, or disable request. Honor any explicit deletion authorization
already given, and inspect the exact affected paths before acting.
