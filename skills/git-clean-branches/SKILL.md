---
name: git-clean-branches
description: Safely identify and clean up merged or stale Git branches with a dry-run-first workflow; supports custom --base refs, protected branch patterns via git config, and optional remote branch deletion. Use when the user runs $git-clean-branches ... or asks to prune merged/stale branches (treat $git-cleanBranches as a legacy alias mention).
metadata:
  short-description: Safe merged/stale branch cleanup (dry-run by default)
  version: 1.0.0
---

# Git Clean Branches

Use the bundled Python script to preview and (optionally) delete merged or stale branches safely.

## Quick Start

Map a skill invocation like `$git-clean-branches --stale 90` to:

```bash
python3 "scripts/git_clean_branches.py" --stale 90
```

More examples:

```bash
python3 "scripts/git_clean_branches.py" --dry-run
python3 "scripts/git_clean_branches.py" --stale 90
python3 "scripts/git_clean_branches.py" --base "release/v2.1" --remote
python3 "scripts/git_clean_branches.py" --base "release/v2.1" --remote --yes
python3 "scripts/git_clean_branches.py" --force "outdated-feature" --yes
```

## Safety model

- Default behavior is **preview-only**: the script never deletes unless `--yes` is provided.
- `--dry-run` always wins (even with `--yes`).
- Local deletions use `git branch -d` by default; `--force` switches to `-D`.

## Options

- `--base <ref>`: Base branch/ref for merged detection (defaults to `main`, then `master`, else `HEAD`).
- `--stale <days>`: Also consider branches whose last commit is older than N days.
- `--remote`: Also consider remote branches (prefers `origin`, else first remote).
- `--dry-run`: Preview only (never delete).
- `--yes`: Apply deletions (required to actually delete).
- `--force`: Use force deletion for local branches (`git branch -D`).
- `<branches...>`: Optional explicit local branches to delete (guarded by `--force` + `--yes`).

## Protected branches (configure once)

The script reads protection patterns from Git config key `branch.cleanup.protected` (supports globs):

```bash
git config --add branch.cleanup.protected "develop"
git config --add branch.cleanup.protected "release/*"
git config --get-all branch.cleanup.protected
```

For the full spec and rationale, see `references/git-clean-branches-spec.md`.

## Resources

- `scripts/git_clean_branches.py`: compute a cleanup plan and optionally apply it
- `references/git-clean-branches-spec.md`: detailed behavior, options, and examples
