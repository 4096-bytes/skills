# Git Clean Branches — Spec

Safely identify and clean up merged or stale Git branches.

The original command name in the source prompt was `/git-cleanBranches` (and some prompts may mention `$git-cleanBranches`). Codex skills are normalized to hyphen-case, so the canonical invocation for this skill is:

```text
$git-clean-branches
```

This skill is implemented by `scripts/git_clean_branches.py`.

## Usage

```bash
# [Safest] Preview branches without executing any deletions
$git-clean-branches --dry-run

# Preview local branches that are merged to main/master and inactive for over 90 days
$git-clean-branches --stale 90

# Clean local and remote branches merged to release/v2.1 (auto-confirm)
$git-clean-branches --base "release/v2.1" --remote --yes

# [Dangerous] Force delete a specific unmerged local branch
$git-clean-branches --force "outdated-feature" --yes
```

## Options

- `--base <branch|ref>`: Base ref for merge detection (defaults to repository `main`/`master`, else `HEAD`).
- `--stale <days>`: Consider branches with last commit older than N days (disabled by default).
- `--remote`: Also include remote branches (prefers `origin`, else first remote).
- `--dry-run`: Preview only; never delete anything (overrides `--yes`).
- `--yes`: Apply deletions (required to actually delete anything).
- `--force`: Use `git branch -D` for local deletions (even if unmerged).
- `<branches...>`: Optional explicit local branches to delete (requires `--force` + `--yes`).

## What This Skill Does

1. **Safety checks**
   - Confirms the current directory is inside a Git work tree.
   - Reads protected branch patterns from Git config key `branch.cleanup.protected`.
   - Determines a base ref from `--base` or auto-detected `main`/`master`/`HEAD`.

2. **Analysis**
   - **Merged branches**: Finds local branches fully merged into `--base`.
   - **Stale branches** (optional): If `--stale <days>` is set, finds branches whose last commit is older than N days.
   - **Remote branches** (optional): With `--remote`, includes `origin/<branch>` (or first remote) for the same merged/stale checks.
   - Excludes:
     - the base branch,
     - the currently checked-out branch,
     - any branch matching protection patterns.

3. **Report**
   - Prints separate lists for merged vs stale candidates (local and remote).

4. **Execute (only with `--yes` and without `--dry-run`)**
   - Local:
     - default: `git branch -d <branch>`
     - with `--force`: `git branch -D <branch>`
   - Remote (with `--remote`):
     - `git push <remote> --delete <branch>`

## Configuration (Protect Branches)

To prevent accidental deletion of important branches (e.g., `develop`, `release/*`), add protection rules to the repo’s Git config:

```bash
git config --add branch.cleanup.protected "develop"
git config --add branch.cleanup.protected "release/*"
git config --get-all branch.cleanup.protected
```

## Best Practices

- Prefer previewing first; only apply with `--yes` after reviewing the printed plan.
- Avoid `--force` unless you are certain the branch is safe to delete.
- Notify your team before deleting shared remote branches (especially in long-lived release workflows).
