#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class GitCommitError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileChange:
    status: str
    path: str
    path2: str | None = None

    def primary_path(self) -> str:
        return self.path2 or self.path


@dataclass(frozen=True)
class RepoContext:
    cwd: Path
    toplevel: Path
    commit_editmsg_path: Path


EMOJI_BY_TYPE: dict[str, str] = {
    "feat": "✨",
    "fix": "🐛",
    "docs": "📝",
    "style": "🎨",
    "refactor": "♻️",
    "perf": "⚡️",
    "test": "✅",
    "chore": "🔧",
    "ci": "👷",
    "revert": "⏪️",
}


def _run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        check=check,
        capture_output=capture_output,
        text=True,
    )


def _git(args: list[str], *, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, check=check)


def _git_stdout(args: list[str], *, cwd: Path) -> str:
    proc = _git(args, cwd=cwd, check=True)
    return proc.stdout.strip()


def _resolve_path(p: Path, *, base: Path) -> Path:
    if p.is_absolute():
        return p.resolve(strict=False)
    return (base / p).resolve(strict=False)


def _ensure_git_repo(cwd: Path) -> None:
    proc = _git(["rev-parse", "--is-inside-work-tree"], cwd=cwd, check=False)
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        raise GitCommitError("Not inside a Git work tree (git rev-parse --is-inside-work-tree failed).")


def _get_repo_context(cwd: Path) -> RepoContext:
    _ensure_git_repo(cwd)

    toplevel_raw = Path(_git_stdout(["rev-parse", "--show-toplevel"], cwd=cwd))
    toplevel = _resolve_path(toplevel_raw, base=cwd)

    editmsg_rel = Path(_git_stdout(["rev-parse", "--git-path", "COMMIT_EDITMSG"], cwd=cwd))
    commit_editmsg_path = _resolve_path(editmsg_rel, base=cwd)

    return RepoContext(cwd=cwd, toplevel=toplevel, commit_editmsg_path=commit_editmsg_path)


def _status_porcelain(cwd: Path) -> list[str]:
    proc = _git(["status", "--porcelain"], cwd=cwd, check=True)
    return [line.rstrip("\n") for line in proc.stdout.splitlines() if line.strip()]


def _is_unmerged(xy: str) -> bool:
    if len(xy) != 2:
        return False
    if xy == "??":
        return False
    conflict_pairs = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}
    return xy in conflict_pairs


def _parse_status(
    lines: list[str],
) -> tuple[list[str], list[str], list[str], list[str]]:
    staged: list[str] = []
    unstaged: list[str] = []
    unmerged: list[str] = []
    untracked: list[str] = []

    for line in lines:
        if len(line) < 3:
            continue
        if line.startswith("?? "):
            untracked.append(line[3:])
            continue
        xy = line[:2]
        path = line[3:]
        if _is_unmerged(xy):
            unmerged.append(path)
        if xy[0] != " ":
            staged.append(path)
        if xy[1] != " ":
            unstaged.append(path)

    return staged, unstaged, unmerged, untracked


def _diff_name_status_z(*, cwd: Path, cached: bool) -> list[FileChange]:
    args = ["diff", "--name-status", "-z"]
    if cached:
        args.insert(1, "--cached")
    proc = _git(args, cwd=cwd, check=True)
    raw = proc.stdout
    if not raw:
        return []

    parts = raw.split("\0")
    changes: list[FileChange] = []
    i = 0
    while i < len(parts):
        token = parts[i]
        i += 1
        if not token:
            continue

        status = token.strip()
        if status.startswith(("R", "C")):
            if i + 1 >= len(parts):
                break
            old_path = parts[i]
            new_path = parts[i + 1]
            i += 2
            changes.append(FileChange(status=status, path=old_path, path2=new_path))
            continue

        if i >= len(parts):
            break
        path = parts[i]
        i += 1
        changes.append(FileChange(status=status, path=path))

    return changes


def _diff_text(*, cwd: Path, cached: bool) -> str:
    args = ["diff"]
    if cached:
        args.append("--cached")
    proc = _git(args, cwd=cwd, check=True)
    return proc.stdout


def _diff_shortstat(*, cwd: Path, cached: bool) -> tuple[int, int]:
    args = ["diff", "--shortstat"]
    if cached:
        args.insert(1, "--cached")
    proc = _git(args, cwd=cwd, check=True)
    text = proc.stdout.strip()
    if not text:
        return 0, 0

    insertions = 0
    deletions = 0
    m_ins = re.search(r"(\d+) insertions?\(\+\)", text)
    m_del = re.search(r"(\d+) deletions?\(-\)", text)
    if m_ins:
        insertions = int(m_ins.group(1))
    if m_del:
        deletions = int(m_del.group(1))
    return insertions, deletions


def _categorize_path(path: str) -> str:
    p = path.lower()
    if p.endswith((".md", ".rst", ".adoc")) or p.startswith("docs/") or "/docs/" in p:
        return "docs"
    if p.startswith(".github/") or p.startswith(".gitlab/") or p.startswith(".circleci/"):
        return "ci"
    if (
        p.startswith("test/")
        or p.startswith("tests/")
        or "/__tests__/" in p
        or "/test/" in p
        or "/tests/" in p
        or p.endswith((".spec.ts", ".spec.tsx", ".spec.js", ".test.ts", ".test.tsx", ".test.js"))
    ):
        return "test"
    config_names = {
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "eslint.config.js",
        ".eslintrc",
        ".prettierrc",
        "prettier.config.js",
    }
    if Path(p).name in config_names or p.endswith((".lock", ".toml", ".yaml", ".yml")):
        return "chore"
    return "code"

def _infer_type(
    *,
    changes: list[FileChange],
    diff_text: str,
    override: str | None,
) -> str:
    if override:
        return override
    if not changes:
        return "chore"

    scores: dict[str, int] = {k: 0 for k in EMOJI_BY_TYPE}
    for ch in changes:
        cat = _categorize_path(ch.primary_path())
        if cat in ("docs", "ci", "test"):
            scores[cat] += 3
        elif cat == "chore":
            scores["chore"] += 2
        else:
            scores["feat"] += 1
            scores["fix"] += 1
            scores["refactor"] += 1

        if ch.status.startswith("A"):
            scores["feat"] += 2
        if ch.status.startswith("D"):
            scores["chore"] += 1

    added_lines = [line[1:].strip() for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++")]
    joined = "\n".join(added_lines).lower()
    if re.search(r"\b(fix|bug|error|prevent|handle|guard)\b", joined):
        scores["fix"] += 3
    if re.search(r"\b(refactor|extract|rename|move)\b", joined):
        scores["refactor"] += 3
    if re.search(r"\b(optimi[sz]e|perf|performance)\b", joined):
        scores["perf"] += 3
    if re.search(r"\b(prettier|format|lint)\b", joined):
        scores["style"] += 2

    best = max(scores.items(), key=lambda kv: kv[1])[0]
    return best


def _infer_scope(*, paths: list[str], override: str | None) -> str | None:
    if override:
        return override
    if not paths:
        return None

    excluded = {"src", "test", "tests", "docs", ".github", ".gitlab", ".circleci"}
    candidates: list[str] = []
    for path in paths:
        parts = [p for p in path.split("/") if p]
        if not parts:
            continue
        if parts[0] == "src" and len(parts) >= 2:
            seg = parts[1]
        else:
            seg = parts[0]
        if seg in excluded:
            continue
        candidates.append(seg)

    if not candidates:
        return None

    counts: dict[str, int] = {}
    for seg in candidates:
        counts[seg] = counts.get(seg, 0) + 1

    top = max(counts.items(), key=lambda kv: kv[1])
    if top[1] / len(candidates) < 0.6:
        return None
    return top[0]


def _truncate(s: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    if max_len == 1:
        return s[:1]
    return s[: max_len - 1] + "…"


def _build_subject(
    *,
    type_: str,
    paths: list[str],
    changes: list[FileChange],
) -> str:
    if type_ == "feat":
        verb = "add"
    elif type_ == "fix":
        verb = "fix"
    elif type_ == "docs":
        verb = "update docs"
    elif type_ == "refactor":
        verb = "refactor"
    elif type_ == "perf":
        verb = "improve performance"
    elif type_ == "style":
        verb = "format"
    elif type_ == "test":
        verb = "update tests"
    elif type_ == "ci":
        verb = "update ci"
    else:
        verb = "update"

    if len(paths) == 1:
        return f"{verb} {paths[0]}"

    cats = {_categorize_path(p) for p in paths}
    if cats == {"docs"}:
        return "update documentation"
    if cats == {"test"}:
        return "update tests"
    if cats == {"ci"}:
        return "update ci configuration"
    if cats <= {"chore"}:
        return "update configuration"
    return "update changes"


def _build_body(*, paths: list[str]) -> list[str]:
    if not paths:
        return ["- update changes"]

    groups: dict[str, list[str]] = {}
    for p in paths:
        groups.setdefault(_categorize_path(p), []).append(p)

    def bullet_for(cat: str) -> str:
        if cat == "docs":
            return "- update documentation"
        if cat == "test":
            return "- update tests"
        if cat == "ci":
            return "- update ci workflows"
        if cat == "chore":
            return "- update project configuration"
        return "- update implementation"

    ordered = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    bullets = [bullet_for(cat) for cat, _ in ordered[:3]]
    return bullets or ["- update changes"]


def _format_commit_message(
    *,
    emoji: bool,
    type_: str,
    scope: str | None,
    subject: str,
    body: list[str],
    breaking_footer: str | None,
) -> str:
    scope_part = f"({scope})" if scope else ""
    header_prefix = f"{type_}{scope_part}"
    if breaking_footer and "!" not in header_prefix:
        header_prefix += "!"

    header = f"{header_prefix}: {subject}"
    if emoji:
        icon = EMOJI_BY_TYPE.get(type_, "")
        if icon:
            header = f"{icon} {header}"

    max_subject = 72 - (len(header) - len(subject))
    subject = _truncate(subject, max_subject)
    header = f"{header_prefix}: {subject}"
    if emoji:
        icon = EMOJI_BY_TYPE.get(type_, "")
        if icon:
            header = f"{icon} {header}"

    lines: list[str] = [header, "", *body]
    if breaking_footer:
        lines.extend(["", breaking_footer])
    return "\n".join(lines).rstrip() + "\n"


def _detect_breaking_footer(diff_text: str) -> str | None:
    for line in diff_text.splitlines():
        if line.startswith("+BREAKING CHANGE:"):
            return line[1:].rstrip()
    return None


def _suggest_split(
    *,
    paths: list[str],
    changed_lines: int,
) -> list[tuple[str, list[str]]]:
    if not paths:
        return []

    cats = {_categorize_path(p) for p in paths}
    tops = {p.split("/", 1)[0] for p in paths if "/" in p} | {p for p in paths if "/" not in p}

    looks_mixed = len(cats) >= 2 and ("code" in cats) and (cats - {"code"})
    looks_large = changed_lines >= 300
    looks_multi_top = len(tops) >= 3

    if not (looks_mixed or looks_large or looks_multi_top):
        return []

    groups: dict[str, list[str]] = {}
    for p in paths:
        cat = _categorize_path(p)
        if cat != "code":
            groups.setdefault(cat, []).append(p)
            continue
        top = p.split("/", 1)[0]
        groups.setdefault(f"code:{top}", []).append(p)

    ordered = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    return [(k, v) for k, v in ordered]


def _build_commit_command(
    *,
    ctx: RepoContext,
    no_verify: bool,
    amend: bool,
    signoff: bool,
) -> str:
    parts = ["git", "commit", "-F", str(ctx.commit_editmsg_path)]
    if amend:
        parts.append("--amend")
    if signoff:
        parts.append("-s")
    if no_verify:
        parts.append("--no-verify")
    return " ".join(parts)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="git_commit.py",
        description="Generate a Conventional Commits draft message from Git diffs only.",
    )
    parser.add_argument("--no-verify", action="store_true", help="Skip local Git hooks (commit-msg etc).")
    parser.add_argument("--all", action="store_true", help="If index is empty, run git add -A.")
    parser.add_argument("--amend", action="store_true", help="Amend the previous commit (git commit --amend).")
    parser.add_argument("--signoff", action="store_true", help="Add Signed-off-by line (git commit -s).")
    parser.add_argument("--emoji", action="store_true", help="Prefix the commit header with an emoji.")
    parser.add_argument("--scope", type=str, default=None, help="Override inferred scope.")
    parser.add_argument("--type", type=str, default=None, help="Override inferred type.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    cwd = Path.cwd()

    try:
        ctx = _get_repo_context(cwd)
        status_lines = _status_porcelain(ctx.toplevel)
        staged, unstaged, unmerged, untracked = _parse_status(status_lines)

        if unmerged:
            paths = "\n".join(f"- {p}" for p in unmerged[:20])
            raise GitCommitError(f"Unmerged paths detected; resolve conflicts first:\n{paths}")

        if not staged and args.all and (unstaged or untracked):
            _git(["add", "-A"], cwd=ctx.toplevel, check=True)
            status_lines = _status_porcelain(ctx.toplevel)
            staged, unstaged, unmerged, untracked = _parse_status(status_lines)

        if not staged and not (unstaged or untracked):
            print("[info] No changes to commit (index and working tree are clean).")
            return 0

        cached = bool(staged)
        changes = _diff_name_status_z(cwd=ctx.toplevel, cached=cached)
        if not cached and untracked:
            changes.extend(FileChange(status="A", path=p) for p in untracked)
        diff_text = _diff_text(cwd=ctx.toplevel, cached=cached)
        insertions, deletions = _diff_shortstat(cwd=ctx.toplevel, cached=cached)
        changed_lines = insertions + deletions

        paths = [c.primary_path() for c in changes]
        breaking_footer = _detect_breaking_footer(diff_text)
        type_ = _infer_type(changes=changes, diff_text=diff_text, override=args.type)
        scope = _infer_scope(paths=paths, override=args.scope)
        subject = _build_subject(type_=type_, paths=paths, changes=changes)
        body = _build_body(paths=paths)
        message = _format_commit_message(
            emoji=args.emoji,
            type_=type_,
            scope=scope,
            subject=subject,
            body=body,
            breaking_footer=breaking_footer,
        )

        ctx.commit_editmsg_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.commit_editmsg_path.write_text(message, encoding="utf-8")

        print(f"[ok] Wrote commit message draft: {ctx.commit_editmsg_path}")
        print()
        print(message, end="")

        if not staged:
            print(
                "[warn] Index is empty: this draft is based on unstaged changes. Prefer grouping with git add <paths> first, or use --all."
            )

        suggested = _suggest_split(paths=paths, changed_lines=changed_lines)
        if suggested:
            print()
            print("[hint] Changes look like multiple concerns; consider splitting commits:")
            for key, items in suggested[:6]:
                show = " ".join(sorted({p.split('/', 1)[0] for p in items})[:6])
                print(f"- {key} ({len(items)} files) -> git add {show}")

        print()
        print("[next] Suggested commit command:")
        print(_build_commit_command(ctx=ctx, no_verify=args.no_verify, amend=args.amend, signoff=args.signoff))
        return 0
    except GitCommitError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
