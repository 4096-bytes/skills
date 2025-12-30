---
name: git-commit
description: Analyze staged/unstaged changes using Git only and generate a Conventional Commits draft message (optional emoji); suggest splitting when changes look mixed or large; keep local Git hooks enabled by default (use --no-verify to skip). Use when the user runs $git-commit ... or asks for Git-only Conventional Commit message generation.
metadata:
  short-description: Git-only Conventional Commits draft generator
---

# Git Commit (Git-only Conventional Commits)

Use Git (no npm/pnpm/yarn, build scripts, or other tooling) to read changes, generate a Conventional Commits-style commit message draft, and suggest splitting commits when appropriate.

This skill prefers the bundled script `scripts/git_commit.py`, which writes the draft to Git's `COMMIT_EDITMSG` and prints a suggested `git commit ...` command.

## Quick Start

Map the user's command (e.g. `$git-commit --scope ui --type feat --emoji`) to the script:

```bash
python3 "scripts/git_commit.py" --scope "ui" --type "feat" --emoji
```

More examples:

```bash
python3 "scripts/git_commit.py"                          # generate a draft (prefers staged changes)
python3 "scripts/git_commit.py" --all                    # if index is empty, run git add -A then draft
python3 "scripts/git_commit.py" --no-verify              # generate draft and suggest committing with --no-verify
python3 "scripts/git_commit.py" --emoji                  # prefix the header with an emoji
python3 "scripts/git_commit.py" --scope "ui" --type "fix"
python3 "scripts/git_commit.py" --amend --signoff
```

The script will:

- Use Git commands only to read status/diffs
- Write the draft to `COMMIT_EDITMSG` (no direct edits to working tree files)
- Print a suggested `git commit ...` command (hooks enabled by default; use `--no-verify` when needed)

## Constraints (Git-only)

Do not run package manager or build commands (e.g. `pnpm`/`npm`/`yarn`/`make`). Only Git is used to inspect changes and perform the commit.

Common Git commands (with necessary args) include:

- `git rev-parse ...` (validate repository state, resolve Git paths)
- `git status --porcelain`
- `git diff` / `git diff --cached`
- `git add` (only when user requests `--all` or explicitly wants to stage specific paths)
- `git restore --staged <paths>` (undo staging safely)
- `git commit ...` (commit using the draft; hooks enabled by default)

## Workflow (Recommended)

1. **Repository & conflict checks**
   - Confirm you're in a repo: `git rev-parse --is-inside-work-tree`
   - If porcelain shows conflicts (`UU/AA/...`), resolve them before committing

2. **Read changes (prefer staged)**
   - If the index is empty:
     - With `--all`: run `git add -A`
     - Otherwise: generate a draft from unstaged changes and advise grouping with `git add <paths>` first

3. **Split suggestions**
   - Suggest splitting when changes span multiple concerns (code + docs/tests/CI/config), span multiple top-level dirs, or are large
   - Provide actionable grouping hints (e.g. suggested `git add <paths>` sets)

4. **Generate commit message (Conventional Commits, optional emoji)**
   - Header: `[<emoji>] <type>(<scope>)?: <subject>` (first line <= 72 chars)
   - Body: blank line, then `- ` list (prefer <= 3 bullets), imperative verb-first sentences
   - Prohibit label-style colon formats (e.g. `Feature: ...`, `Impl: ...`)

5. **Commit**
   - Prefer `git commit -F <COMMIT_EDITMSG>` so local hooks run by default
   - Add `--no-verify` only when explicitly requested
   - Pass through `--amend` and `--signoff` as requested

## Reference

See `references/git-commit-spec.md` for the full spec, emoji mapping, splitting guidelines, and examples.

## Resources

- `scripts/git_commit.py`: generate a draft in `COMMIT_EDITMSG` and print a suggested `git commit ...` command
- `references/git-commit-spec.md`: full constraints and examples
