# 4096bytes Skills

A small collection of reusable agent skills (Codex CLI compatible).

## What is a “skill”?

A skill is a self-contained, versioned workflow that teaches the agent how to do a specific task reliably.
In practice, each skill lives in its own directory and is defined by a `SKILL.md` file (metadata + instructions),
optionally backed by scripts and reference specs.

### Learn more

- [Using skills in Codex](https://developers.openai.com/codex/skills)
- [Agent Skills open standard](https://agentskills.io/home)

## Included skills

### `git-commit`
Install skills from this repo:

```text
$skill-installer install https://github.com/4096-bytes/skills/tree/main/skills/git-commit
```

Generates a Conventional Commits-style draft message using Git only (no build tools), preferring staged changes.
It writes the draft to Git’s `COMMIT_EDITMSG` and prints a suggested `git commit ...` command.

- Entry: `skills/git-commit/SKILL.md`
- Script: `skills/git-commit/scripts/git_commit.py`

Natural-language examples (prompts you can give the agent):

- “I’ve staged a focused change. Draft a Conventional Commit message for what’s in the index.”
  - `$git-commit`
- “Treat this as a fix in scope `cli`, and add an emoji prefix.”
  - `$git-commit --type "fix" --scope "cli" --emoji`
- “Stage everything and generate the draft for me.”
  - `$git-commit --all`
- “This is a small follow‑up; amend the previous commit (and include DCO sign‑off).”
  - `$git-commit --amend --signoff`
- “Generate the draft, but I need to commit without running local hooks.”
  - `$git-commit --no-verify`

### `git-worktree`

Install skills from this repo:

```text
$skill-installer install https://github.com/4096-bytes/skills/tree/main/skills/git-worktree
```

Manages Git worktrees under `../.atmu/<project-name>/` with safe path handling and optional IDE opening.
Includes helpers to migrate uncommitted changes via stash and to copy gitignored `.env` / `.env.*` files into new worktrees.

- Entry: `skills/git-worktree/SKILL.md`
- Script: `skills/git-worktree/scripts/git_worktree.py`

Natural-language examples (prompts you can give the agent):

- “Create an isolated worktree for a new feature branch called `feat/ui` and open it in my IDE.”
  - `$git-worktree add "feature-ui" -b "feat/ui" -o`
- “I want the worktree folder name to be `hotfix`, but the branch name to be `fix/login`.”
  - `$git-worktree add "hotfix" -b "fix/login"`
- “Move my uncommitted work from `main` into the `feature-ui` worktree.”
  - `$git-worktree migrate "feature-ui" --from "main"`
- “I’m done with `feature-ui`; remove the worktree and clean up.”
  - `$git-worktree remove "feature-ui"`
- “I deleted a worktree folder manually; prune stale worktree references.”
  - `$git-worktree prune`

### `git-clean-branches`

Install skills from this repo:

```text
$skill-installer install https://github.com/4096-bytes/skills/tree/main/skills/git-clean-branches
```

Safely identifies merged and/or stale Git branches and prints a deletion plan by default (dry-run).
Requires `--yes` to apply deletions, supports protected branch patterns via `git config branch.cleanup.protected`,
and can optionally delete remote branches as well.

- Entry: `skills/git-clean-branches/SKILL.md`
- Script: `skills/git-clean-branches/scripts/git_clean_branches.py`

Natural-language examples (prompts you can give the agent):

- “Show me which branches are merged into main and safe to delete.”
  - `$git-clean-branches --dry-run`
- “Find branches inactive for 90+ days and show what would be deleted.”
  - `$git-clean-branches --stale 90`
- “Delete merged branches against release/v2.1, including remote branches.”
  - `$git-clean-branches --base "release/v2.1" --remote --yes`
- “Force-delete a specific local branch that I know is obsolete.”
  - `$git-clean-branches --force "outdated-feature" --yes`

## License

MIT (see `LICENSE`).
