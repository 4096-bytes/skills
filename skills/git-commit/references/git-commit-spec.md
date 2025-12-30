# Git Commit (Git-only Conventional Commits) Spec

Goal: Use Git only to read changes (staged/unstaged), decide whether commits should be split, and generate a Conventional Commits-style commit message (optional emoji).

## Usage

```bash
$git-commit
$git-commit --no-verify
$git-commit --emoji
$git-commit --all --signoff
$git-commit --amend
$git-commit --scope ui --type feat --emoji
```

Options:

- `--no-verify`: Skip local Git hooks (`pre-commit`/`commit-msg`, etc.).
- `--all`: If the index is empty, run `git add -A` automatically.
- `--amend`: Amend the previous commit (`git commit --amend`).
- `--signoff`: Add `Signed-off-by` (DCO workflows).
- `--emoji`: Prefix the commit header with an emoji (omit for plain text).
- `--scope <scope>`: Override inferred scope (e.g. `ui`, `docs`, `api`).
- `--type <type>`: Override inferred type (e.g. `feat`, `fix`, `docs`).

## Behavior

### 1) Repository state checks

- Must confirm you're inside a Git repository using `git rev-parse --is-inside-work-tree`.
- If conflicts are present (`git status --porcelain` shows `UU/AA/...`), stop and resolve conflicts first.

### 2) Change detection (staged/unstaged)

- Use `git status --porcelain` to detect staged/unstaged changes.
- Default to generating the message from the **index** (`git diff --cached`).
- If the index is empty:
  - With `--all`: run `git add -A` and continue.
  - Without `--all`: do not commit automatically; you may still analyze unstaged changes to draft a message, but advise the user to group changes with `git add <paths>` first (or rerun with `--all`).

### 3) Split suggestions (heuristics)

Suggest splitting (with actionable path grouping hints) when:

- **Mixed concerns**: code changes mixed with docs/tests/CI/config.
- **Mixed semantic types**: `feat`/`fix`/`refactor` mixed together.
- **Wide directory spread**: changes across multiple top-level directories/packages.
- **Large diffs**: e.g. > 300 changed lines, or multiple top-level dirs with mixed file categories.

### 4) Commit message generation (Conventional + optional emoji)

#### Header

- Format: `[<emoji>] <type>(<scope>)?: <subject>`
- First line length: <= 72 characters
- Only add emoji when `--emoji` is provided
- `--type` / `--scope` must override inference when provided

#### Body

- Must have a blank line after the subject
- Use bullet list format, each item starts with `- `
- Each item must be an imperative, verb-first sentence (e.g. `add...`, `fix...`, `update...`)
- Prohibit label-style colon formats (e.g. `Feature: ...`, `Impl: ...`)
- Recommend <= 3 bullets describing motivation, implementation, or impact

#### Footer (optional)

- Add a blank line after the body
- For breaking changes:
  - `BREAKING CHANGE: <description>`, or
  - Add `!` after the type (e.g. `feat!:`)
- Other footers should use Git trailer format (e.g. `Closes #123`, `Refs: #456`, `Reviewed-by: Name`)

#### Draft writing

- Write the generated draft to Git's `COMMIT_EDITMSG` (e.g. `.git/COMMIT_EDITMSG`) for `git commit -F`.

### 5) Execute the commit

Recommended command (hooks enabled by default):

```bash
git commit -F .git/COMMIT_EDITMSG
```

With options:

- `--no-verify`: `git commit ... --no-verify`
- `--signoff`: `git commit ... -s`
- `--amend`: `git commit ... --amend`

### 6) Safe rollback (index only)

If you staged the wrong paths:

```bash
git restore --staged <paths>
```

This only affects the index; it does not modify working tree file contents.

## Type to emoji mapping (`--emoji`)

- ✨ `feat`: New feature
- 🐛 `fix`: Bug fix
- 📝 `docs`: Documentation and comments
- 🎨 `style`: Formatting only (no semantic changes)
- ♻️ `refactor`: Refactoring (no new features, no bug fixes)
- ⚡️ `perf`: Performance improvements
- ✅ `test`: Add/fix tests
- 🔧 `chore`: Tooling/config/misc
- 👷 `ci`: CI/CD configuration and scripts
- ⏪️ `revert`: Revert commits
- 💥 `feat`: Breaking changes (explain with `BREAKING CHANGE:`)

## Examples

With emoji header:

```text
✨ feat(ui): add user authentication flow
🐛 fix(api): handle token refresh race condition
📝 docs: update API usage examples
♻️ refactor(core): extract retry logic into helper
✅ test: add unit tests for rate limiter
🔧 chore: update repository settings
⏪️ revert: revert "feat(core): introduce streaming API"
```

With body:

```text
feat(auth): add OAuth2 login flow

- implement Google and GitHub third-party login
- add user authorization callback handling
- improve login state persistence logic

Closes #42
```

Breaking change:

```text
feat(api)!: redesign authentication API

- migrate from session-based to JWT authentication
- update all endpoint signatures
- remove deprecated login methods

BREAKING CHANGE: authentication API has been redesigned and all clients must update
```
