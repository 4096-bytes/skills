---
name: git-worktree
description: Manage Git worktrees under ../.atmu/{project-name}/ with add/list/remove/prune/migrate; infer the main repo path even when run inside a worktree and use absolute paths to avoid nested directories; default to branching from main/master; copy gitignored .env/.env.* (excluding .env.example) into new worktrees; migrate uncommitted changes via stash. Use when the user runs $git-worktree ... or asks about Git worktrees / parallel branches / isolated workspaces / migrating uncommitted changes.
metadata:
  short-description: Smart Git worktree management with .atmu isolation.
  version: 1.0.0
---

# Git Worktree (.atmu Convention)

Use a bundled Python script to manage Git worktrees under the structured directory `../.atmu/{project-name}/`, including main-repo path inference, optional IDE opening, and change migration.

## Quick Start

Prefer running the bundled script `scripts/git_worktree.py` to avoid repeatedly hand-writing Git commands and path logic.

Map a skill invocation like `$git-worktree add feature-ui -o` to:

```bash
python3 "scripts/git_worktree.py" add "feature-ui" -o
```

More examples:

```bash
python3 "scripts/git_worktree.py" add "feature-ui"                      # new branch feature-ui (based on main/master)
python3 "scripts/git_worktree.py" add "hotfix" -b "fix/login" -o        # path hotfix, branch fix/login, open IDE
python3 "scripts/git_worktree.py" list                                  # list worktrees
python3 "scripts/git_worktree.py" remove "feature-ui"                   # remove a worktree
python3 "scripts/git_worktree.py" prune                                 # prune stale worktree references
python3 "scripts/git_worktree.py" migrate "feature-ui" --from "main"    # migrate uncommitted changes from main (stash push/pop)
python3 "scripts/git_worktree.py" migrate "feature-ui" --stash          # pop current stash onto feature-ui
```

## Key Guarantees

- **Main repo inference**: Whether run in the main repo or any worktree, derive the main repo via `git rev-parse --git-common-dir`.
- **Absolute paths**: Always create worktrees with absolute paths to avoid nested worktree roots (e.g. `.atmu/{project}/.atmu/{project}/...`).
- **Structured layout**: Worktrees live under `../.atmu/{project-name}/{path}` (sibling directory of the main repo).
- **Default branching**: If `add` omits `-b`, branch defaults to `path`; base ref prefers `main`, then `master`, then `HEAD`.

## Subcommands

### add

- Create the worktree at `../.atmu/{project-name}/{path}`.
- After creation, try to copy gitignored env files from the main repo root: `.env` and `.env.*` (excluding `.env.example`).
  - Uses `shutil.copy2` to preserve permissions and timestamps.
- IDE: `-o/--open` opens immediately; otherwise it prompts only in interactive terminals.

### migrate

- Migrate uncommitted changes: `migrate <target> --from main|<path>`
  - Implemented via `git stash push -u` then `git stash pop` in the target worktree.
  - Target worktree must be clean; conflicts are resolved via normal Git conflict workflows.
- Migrate stash: `migrate <target> --stash` (runs `git stash pop` in the target).

### list/remove/prune

- `list`: print all worktrees (path, branch/detached, HEAD).
- `remove`: remove a worktree and additionally run `worktree prune`.
- `prune`: prune stale worktree references.

## IDE Configuration (Optional)

The script reads Git config from the main repo:

- `worktree.ide.preferred`: `vscode|code|cursor|webstorm|sublime|vim`
- `worktree.ide.autodetect`: `true|false` (disable autodetection)
- `worktree.ide.custom.<name>`: custom open command (supports `%s` placeholder)

Example:

```bash
git config "worktree.ide.preferred" "sublime"
git config "worktree.ide.custom.sublime" "subl %s"
```

For more details and the original spec, see `references/git-worktree-spec.md`.
