#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class GitWorktreeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoContext:
    main_repo_path: Path
    project_name: str
    worktree_root: Path
    current_toplevel: Path


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        check=check,
        capture_output=capture_output,
        text=True,
    )


def _git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, check=check)


def _git_stdout(args: list[str], *, cwd: Path) -> str:
    proc = _git(args, cwd=cwd, check=True)
    return proc.stdout.strip()


def _git_try_stdout(args: list[str], *, cwd: Path) -> str | None:
    proc = _git(args, cwd=cwd, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _ensure_git_repo(cwd: Path) -> None:
    proc = _git(["rev-parse", "--is-inside-work-tree"], cwd=cwd, check=False)
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        raise GitWorktreeError("Not inside a Git work tree (git rev-parse --is-inside-work-tree failed).")


def _resolve_path(p: Path, *, base: Path | None = None) -> Path:
    if p.is_absolute():
        return p.resolve(strict=False)
    if base is None:
        base = Path.cwd()
    return (base / p).resolve(strict=False)


def _get_repo_context(cwd: Path) -> RepoContext:
    _ensure_git_repo(cwd)

    current_toplevel = Path(_git_stdout(["rev-parse", "--show-toplevel"], cwd=cwd))
    current_toplevel = _resolve_path(current_toplevel, base=cwd)

    git_common_dir = _git_stdout(["rev-parse", "--git-common-dir"], cwd=cwd)
    common_dir_path = _resolve_path(Path(git_common_dir), base=cwd)
    main_repo_path = common_dir_path.parent

    project_name = main_repo_path.name
    worktree_root = (main_repo_path.parent / ".atmu" / project_name).resolve(strict=False)

    return RepoContext(
        main_repo_path=main_repo_path,
        project_name=project_name,
        worktree_root=worktree_root,
        current_toplevel=current_toplevel,
    )


def _is_within(child: Path, parent: Path) -> bool:
    try:
        return child.is_relative_to(parent)
    except AttributeError:
        child_str = str(child)
        parent_str = str(parent)
        return os.path.commonpath([child_str, parent_str]) == parent_str


def _resolve_worktree_path(ctx: RepoContext, user_path: str) -> Path:
    raw = Path(user_path)
    candidate = _resolve_path(raw, base=ctx.worktree_root)
    worktree_root = ctx.worktree_root.resolve(strict=False)
    if not _is_within(candidate, worktree_root):
        raise GitWorktreeError(f"Invalid path: {user_path} (must be within {worktree_root}).")
    return candidate


def _git_ref_exists(ctx: RepoContext, ref: str) -> bool:
    proc = _git(["rev-parse", "--verify", "--quiet", ref], cwd=ctx.main_repo_path, check=False)
    return proc.returncode == 0


def _choose_base_ref(ctx: RepoContext) -> str:
    if _git_ref_exists(ctx, "refs/heads/main"):
        return "main"
    if _git_ref_exists(ctx, "refs/heads/master"):
        return "master"
    return "HEAD"


def _parse_worktree_porcelain(output: str) -> list[dict[str, str | bool]]:
    entries: list[dict[str, str | bool]] = []
    current: dict[str, str | bool] = {}

    def flush() -> None:
        nonlocal current
        if current:
            entries.append(current)
            current = {}

    for line in output.splitlines():
        line = line.rstrip("\n")
        if not line:
            flush()
            continue
        if line == "detached":
            current["detached"] = True
            continue
        if line == "locked":
            current["locked"] = True
            continue
        key, _, value = line.partition(" ")
        if key and value:
            current[key] = value
        else:
            current[line] = True

    flush()
    return entries


def _status_porcelain(repo_path: Path) -> list[str]:
    proc = _git(["status", "--porcelain"], cwd=repo_path, check=True)
    lines = [line.rstrip("\n") for line in proc.stdout.splitlines() if line.strip()]
    return lines


def _copy_env_files(ctx: RepoContext, target_worktree: Path) -> int:
    gitignore = ctx.main_repo_path / ".gitignore"
    if not gitignore.exists():
        return 0

    candidates: list[Path] = []
    env = ctx.main_repo_path / ".env"
    if env.exists() and env.is_file():
        candidates.append(env)

    for p in ctx.main_repo_path.glob(".env.*"):
        if not p.is_file():
            continue
        if p.name == ".env.example":
            continue
        candidates.append(p)

    copied = 0
    for src in candidates:
        rel = src.relative_to(ctx.main_repo_path).as_posix()
        ignored = _git(["check-ignore", "-q", rel], cwd=ctx.main_repo_path, check=False).returncode == 0
        if not ignored:
            continue

        dst = target_worktree / src.name
        if dst.exists():
            print(f"[skip] Destination already exists: {dst}")
            continue
        shutil.copy2(src, dst)
        print(f"[copy] {src.name}")
        copied += 1

    if copied:
        print(f"[info] Copied {copied} env file(s) (based on gitignore rules).")
    return copied


def _get_git_config(ctx: RepoContext, key: str) -> str | None:
    value = _git_try_stdout(["config", "--get", key], cwd=ctx.main_repo_path)
    if value is None or not value.strip():
        return None
    return value.strip()


def _resolve_ide_open_command(ctx: RepoContext, target_worktree: Path) -> list[str] | None:
    preferred = _get_git_config(ctx, "worktree.ide.preferred")
    autodetect = _get_git_config(ctx, "worktree.ide.autodetect")
    if autodetect is not None and autodetect.lower() in {"0", "false", "no"} and not preferred:
        return None

    def from_custom(name: str) -> list[str] | None:
        custom = _get_git_config(ctx, f"worktree.ide.custom.{name}")
        if not custom:
            return None
        parts = shlex.split(custom)
        target = str(target_worktree)
        if any("%s" in part for part in parts):
            return [part.replace("%s", target) for part in parts]
        return [*parts, target]

    def from_known(name: str) -> list[str] | None:
        mapping: dict[str, list[str]] = {
            "vscode": ["code"],
            "code": ["code"],
            "cursor": ["cursor"],
            "webstorm": ["webstorm"],
            "sublime": ["subl"],
            "vim": ["vim"],
        }
        if name not in mapping:
            return None
        exe = mapping[name][0]
        if shutil.which(exe) is None:
            return None
        if exe == "vim":
            return None
        return [exe, str(target_worktree)]

    if preferred:
        preferred = preferred.strip()
        return from_custom(preferred) or from_known(preferred)

    for name in ["code", "cursor", "webstorm", "subl"]:
        if shutil.which(name) is not None:
            return [name, str(target_worktree)]
    return None


def _maybe_open_ide(ctx: RepoContext, target_worktree: Path, *, force: bool) -> None:
    open_cmd = _resolve_ide_open_command(ctx, target_worktree)
    if not open_cmd:
        return

    if not force:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return
        answer = input(f"Open in IDE: {target_worktree}? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            return

    try:
        _run(open_cmd, check=True, capture_output=False)
        print(f"[info] Opened: {target_worktree}")
    except subprocess.CalledProcessError as e:
        raise GitWorktreeError(f"Failed to open IDE: {e}") from e


def cmd_add(ctx: RepoContext, args: argparse.Namespace) -> int:
    if args.detach and args.branch:
        raise GitWorktreeError("--detach cannot be used together with -b/--branch.")

    worktree_path = _resolve_worktree_path(ctx, args.path)
    if worktree_path.exists():
        raise GitWorktreeError(f"Target directory already exists: {worktree_path}")

    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    branch = args.branch or args.path
    base_ref = _choose_base_ref(ctx)

    cmd = ["worktree", "add"]
    if args.no_checkout:
        cmd.append("--no-checkout")
    if args.detach:
        cmd.append("--detach")
    if args.lock:
        cmd.append("--lock")
    if args.track:
        cmd.append("--track")
    if args.guess_remote:
        cmd.append("--guess-remote")

    branch_ref = f"refs/heads/{branch}"
    branch_exists = _git_ref_exists(ctx, branch_ref)
    if args.detach:
        cmd.extend([str(worktree_path), base_ref])
    elif branch_exists:
        cmd.extend([str(worktree_path), branch])
    else:
        cmd.extend(["-b", branch, str(worktree_path), base_ref])

    proc = _git(cmd, cwd=ctx.main_repo_path, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        msg = stderr or stdout or f"git worktree add failed (exit code {proc.returncode})"
        raise GitWorktreeError(msg)

    print(f"[ok] Created worktree: {worktree_path}")
    _copy_env_files(ctx, worktree_path)
    _maybe_open_ide(ctx, worktree_path, force=args.open)
    return 0


def cmd_list(ctx: RepoContext, _args: argparse.Namespace) -> int:
    output = _git_stdout(["worktree", "list", "--porcelain"], cwd=ctx.main_repo_path)
    entries = _parse_worktree_porcelain(output)
    if not entries:
        print("[info] No worktrees found.")
        return 0

    for e in entries:
        path = e.get("worktree", "")
        head = str(e.get("HEAD", ""))[:8]
        branch = e.get("branch", "")
        detached = bool(e.get("detached", False))
        locked = bool(e.get("locked", False))
        branch_str = "detached" if detached else str(branch).removeprefix("refs/heads/")
        flags = []
        if locked:
            flags.append("locked")
        flag_str = f" [{' '.join(flags)}]" if flags else ""
        print(f"{path}  {branch_str}@{head}{flag_str}")
    return 0


def cmd_remove(ctx: RepoContext, args: argparse.Namespace) -> int:
    worktree_path = _resolve_worktree_path(ctx, args.path)
    if not worktree_path.exists():
        raise GitWorktreeError(f"Worktree does not exist: {worktree_path}")

    proc = _git(["worktree", "remove", str(worktree_path)], cwd=ctx.main_repo_path, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        msg = stderr or stdout or f"git worktree remove failed (exit code {proc.returncode})"
        raise GitWorktreeError(msg)

    _git(["worktree", "prune"], cwd=ctx.main_repo_path, check=False)
    print(f"[ok] Removed worktree: {worktree_path}")
    return 0


def cmd_prune(ctx: RepoContext, _args: argparse.Namespace) -> int:
    proc = _git(["worktree", "prune"], cwd=ctx.main_repo_path, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        msg = stderr or stdout or f"git worktree prune failed (exit code {proc.returncode})"
        raise GitWorktreeError(msg)
    print("[ok] Pruned stale worktree references.")
    return 0


def _resolve_source_path(ctx: RepoContext, source: str | None) -> Path:
    if not source:
        return ctx.current_toplevel
    if source == "main":
        return ctx.main_repo_path

    p = Path(source)
    if p.exists():
        return p.resolve(strict=False)

    candidate = _resolve_worktree_path(ctx, source)
    return candidate


def _ensure_same_repo(a: Path, b: Path) -> None:
    a_common = _resolve_path(Path(_git_stdout(["rev-parse", "--git-common-dir"], cwd=a)), base=a)
    b_common = _resolve_path(Path(_git_stdout(["rev-parse", "--git-common-dir"], cwd=b)), base=b)
    if a_common != b_common:
        raise GitWorktreeError("Source/target are not in the same Git repository (git-common-dir mismatch).")


def cmd_migrate(ctx: RepoContext, args: argparse.Namespace) -> int:
    target = _resolve_worktree_path(ctx, args.target)
    if not target.exists():
        raise GitWorktreeError(f"Target worktree does not exist: {target}")

    if args.stash:
        _ensure_same_repo(ctx.main_repo_path, target)
        target_status = _status_porcelain(target)
        if target_status:
            raise GitWorktreeError("Target worktree is not clean; cannot apply stash.")
        stash_list = _git_stdout(["stash", "list"], cwd=ctx.main_repo_path)
        if not stash_list.strip():
            print("[info] No stash entries to apply.")
            return 0
        proc = _git(["stash", "pop"], cwd=target, check=False)
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            msg = stderr or stdout or f"git stash pop failed (exit code {proc.returncode})"
            raise GitWorktreeError(msg)
        print(f"[ok] Applied stash to: {target}")
        return 0

    source = _resolve_source_path(ctx, args.source)
    if not source.exists():
        raise GitWorktreeError(f"Source does not exist: {source}")

    _ensure_same_repo(source, target)

    source_status = _status_porcelain(source)
    if not source_status:
        print("[info] Source has no uncommitted changes; nothing to migrate.")
        return 0

    target_status = _status_porcelain(target)
    if target_status:
        raise GitWorktreeError("Target worktree is not clean; cannot migrate uncommitted changes.")

    print("[info] The following changes will be migrated:")
    for line in source_status[:50]:
        print(f"  {line}")
    if len(source_status) > 50:
        print(f"  ... ({len(source_status)} lines total)")

    message = f"atmu-migrate {source} -> {target}"
    push = _git(["stash", "push", "-u", "-m", message], cwd=source, check=False)
    if push.returncode != 0:
        stderr = (push.stderr or "").strip()
        stdout = (push.stdout or "").strip()
        msg = stderr or stdout or f"git stash push failed (exit code {push.returncode})"
        raise GitWorktreeError(msg)
    if "No local changes to save" in (push.stdout or "") + (push.stderr or ""):
        print("[info] No local changes to migrate.")
        return 0

    pop = _git(["stash", "pop"], cwd=target, check=False)
    if pop.returncode != 0:
        stderr = (pop.stderr or "").strip()
        stdout = (pop.stdout or "").strip()
        msg = stderr or stdout or f"git stash pop failed (exit code {pop.returncode})"
        raise GitWorktreeError(msg)

    print(f"[ok] Migrated uncommitted changes to: {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="git_worktree.py",
        description="Manage Git worktrees under ../.atmu/<project-name>/ (smart paths, optional IDE opening, change migration, env file copying).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Create a worktree (default: new branch from main/master).")
    p_add.add_argument("path", help="Worktree path (relative to .atmu/<project>/).")
    p_add.add_argument("-b", "--branch", help="New/existing branch name (default: path).")
    p_add.add_argument("-o", "--open", action="store_true", help="Open IDE immediately after creation (no prompt).")
    p_add.add_argument("--track", action="store_true", help="Set upstream tracking for a new branch when possible.")
    p_add.add_argument("--guess-remote", action="store_true", help="With --track: try to guess a matching remote branch.")
    p_add.add_argument("--detach", action="store_true", help="Create a detached HEAD worktree.")
    p_add.add_argument("--no-checkout", action="store_true", help="Create without checking out.")
    p_add.add_argument("--lock", action="store_true", help="Lock the worktree (prevents pruning).")

    sub.add_parser("list", help="List all worktrees.")

    p_remove = sub.add_parser("remove", help="Remove a worktree.")
    p_remove.add_argument("path", help="Worktree path (relative to .atmu/<project>/).")

    sub.add_parser("prune", help="Prune stale worktree references.")

    p_migrate = sub.add_parser("migrate", help="Migrate uncommitted changes or stash to a target worktree.")
    p_migrate.add_argument("target", help="Target worktree (relative to .atmu/<project>/).")
    p_migrate.add_argument("--from", dest="source", help="Source: main or a worktree path.", default=None)
    p_migrate.add_argument("--migrate-from", dest="source", help=argparse.SUPPRESS)
    p_migrate.add_argument("--stash", action="store_true", help="Apply current stash to target (stash pop).")
    p_migrate.add_argument("--migrate-stash", dest="stash", action="store_true", help=argparse.SUPPRESS)

    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ctx = _get_repo_context(Path.cwd())

    try:
        if args.command == "add":
            return cmd_add(ctx, args)
        if args.command == "list":
            return cmd_list(ctx, args)
        if args.command == "remove":
            return cmd_remove(ctx, args)
        if args.command == "prune":
            return cmd_prune(ctx, args)
        if args.command == "migrate":
            return cmd_migrate(ctx, args)
        raise GitWorktreeError(f"Unknown command: {args.command}")
    except GitWorktreeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
