# $git-worktree Spec (Reference)

This skill packages a repeatable Git worktree management workflow into a script, and standardizes worktree locations under the main repo's sibling directory: `../.atmu/{project-name}/`.

Note: This is a reference spec. The source of truth is the actual behavior of `scripts/git_worktree.py`.

## Command Shape

Typical usage (skill invocation style):

```bash
$git-worktree add <path>
$git-worktree add <path> -b <branch> -o
$git-worktree list
$git-worktree remove <path>
$git-worktree prune
$git-worktree migrate <target> --from <source>
$git-worktree migrate <target> --stash
```

In this skill, map the above commands to:

```bash
python3 "scripts/git_worktree.py" <subcommand> ...
```

## Design Notes

### 1) Environment check

- Use `git rev-parse --is-inside-work-tree` to verify the current directory is inside a Git repository.

### 2) Main repo inference (critical)

Goal: Even when run from inside a worktree, infer the main repo path and always create worktrees with absolute paths to avoid nesting (e.g. `.../.atmu/project/.atmu/project/path`).

Script logic (conceptually):

- `git rev-parse --git-common-dir` -> resolve the shared `.git` directory
- main repo path = `dirname(git-common-dir)` (the parent directory of `.git`)
- `project-name = basename(main-repo-path)`
- `worktree-root = main-repo-path/../.atmu/project-name`
- actual worktree path = `worktree-root/<path>` (absolute path)

### 3) Worktree operations

Supported subcommands:

- `add`: create a worktree (default: new branch based on main/master)
- `list`: list all worktrees
- `remove`: remove a worktree (and run prune)
- `prune`: prune stale worktree references
- `migrate`: migrate uncommitted changes or stash

### 4) Defaults

- **Branch name**: if `-b` is omitted, branch defaults to `path`
- **Base ref**: prefer `main`, then `master`, then `HEAD`
- **Location**: create worktrees under `../.atmu/{project-name}/`

### 5) Env file copying (.env)

Goal: After creating a worktree, automatically copy env files from the main repo root into the new worktree:

- `.env`
- `.env.*` (excluding `.env.example`)

Criteria: only copy files that are ignored by Git. The script uses `git check-ignore` to respect `.gitignore` (including negation rules).

Copy method: `shutil.copy2` (preserves permissions and timestamps).

### 6) IDE integration

Priority order: VS Code -> Cursor -> WebStorm -> Sublime.

Configurable via Git config:

```bash
git config worktree.ide.preferred sublime
git config worktree.ide.custom.sublime "subl %s"
git config worktree.ide.autodetect true
```

### 7) Change migration (migrate)

Migrating uncommitted changes is implemented via stash (safe and worktree-friendly):

1. Verify source/target belong to the same repo (same `git-common-dir`)
2. Verify the target working tree is clean
3. Source: `git stash push -u -m "<message>"`
4. Target: `git stash pop`

Stash-only migration mode:

- Target: `git stash pop`

Notes:

- Only uncommitted content is migrated (working tree / index / untracked files depending on stash args). Commits are not migrated; use native Git commands like `git cherry-pick` for commits.

## Directory Layout Example

```
parent/
├── your-project/                # main repository
└── .atmu/
    └── your-project/            # worktree root for this repository
        ├── feature-ui/
        ├── hotfix/
        └── debug/
```

## Notes vs. older prompts (script is source of truth)

- The script provides `--no-checkout` (it checks out by default), not a `--checkout` flag.
- `vim` will not be auto-opened by the script (to avoid blocking the terminal).
