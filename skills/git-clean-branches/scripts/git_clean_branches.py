#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


class GitCleanBranchesError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoContext:
    cwd: Path
    current_branch: str | None
    remote: str | None


@dataclass(frozen=True)
class CleanupPlan:
    merged_local: list[str]
    merged_remote: list[str]
    stale_local: list[str]
    stale_remote: list[str]


def _run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    capture_output: bool = True,
    timeout_s: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        check=check,
        capture_output=capture_output,
        text=True,
        timeout=timeout_s,
    )


def _git(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    timeout_s: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, check=check, timeout_s=timeout_s)


def _git_stdout(args: list[str], *, cwd: Path) -> str:
    proc = _git(args, cwd=cwd, check=True)
    return proc.stdout.strip()


def _ensure_git_repo(cwd: Path) -> None:
    proc = _git(["rev-parse", "--is-inside-work-tree"], cwd=cwd, check=False)
    if proc.returncode != 0 or proc.stdout.strip() != "true":
        raise GitCleanBranchesError("Not inside a Git work tree (git rev-parse --is-inside-work-tree failed).")


def _current_branch(cwd: Path) -> str | None:
    proc = _git(["branch", "--show-current"], cwd=cwd, check=False)
    if proc.returncode != 0:
        return None
    name = proc.stdout.strip()
    return name or None


def _remotes(cwd: Path) -> list[str]:
    proc = _git(["remote"], cwd=cwd, check=False)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _resolve_remote(cwd: Path) -> str | None:
    remotes = _remotes(cwd)
    if not remotes:
        return None
    if "origin" in remotes:
        return "origin"
    return remotes[0]


def _try_fetch_all_prune(ctx: RepoContext) -> None:
    if ctx.remote is None:
        return
    try:
        _git(["fetch", "--all", "--prune"], cwd=ctx.cwd, check=False, timeout_s=20.0)
    except subprocess.TimeoutExpired:
        print("[WARN] git fetch --all --prune timed out; continuing with local refs.", file=sys.stderr)


def _local_branch_exists(cwd: Path, branch: str) -> bool:
    proc = _git(["branch", "--list", branch], cwd=cwd, check=False)
    if proc.returncode != 0:
        return False
    return any(line.strip().lstrip("* ").strip() == branch for line in proc.stdout.splitlines())


def _remote_branch_exists(cwd: Path, remote: str, branch: str) -> bool:
    proc = _git(["branch", "-r", "--list", f"{remote}/{branch}"], cwd=cwd, check=False)
    if proc.returncode != 0:
        return False
    wanted = f"{remote}/{branch}"
    return any(line.strip() == wanted for line in proc.stdout.splitlines())


def _default_base_ref(ctx: RepoContext) -> str:
    for candidate in ("main", "master"):
        if _local_branch_exists(ctx.cwd, candidate):
            return candidate
    if ctx.remote is not None:
        for candidate in ("main", "master"):
            if _remote_branch_exists(ctx.cwd, ctx.remote, candidate):
                return f"{ctx.remote}/{candidate}"
    return "HEAD"


def _read_protected_patterns(ctx: RepoContext) -> list[str]:
    proc = _git(["config", "--get-all", "branch.cleanup.protected"], cwd=ctx.cwd, check=False)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _is_protected(branch: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(branch, pat) for pat in patterns)


def _parse_branch_list(output: str) -> list[str]:
    branches: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("* "):
            line = line[2:].strip()
        branches.append(line)
    return branches


def _merged_local(ctx: RepoContext, *, base_ref: str) -> list[str]:
    proc = _git(["branch", "--merged", base_ref], cwd=ctx.cwd, check=False)
    if proc.returncode != 0:
        raise GitCleanBranchesError(f"Failed to list merged local branches against '{base_ref}'.")
    return _parse_branch_list(proc.stdout)


def _merged_remote(ctx: RepoContext, *, base_ref: str) -> list[str]:
    if ctx.remote is None:
        return []
    proc = _git(["branch", "-r", "--merged", base_ref], cwd=ctx.cwd, check=False)
    if proc.returncode != 0:
        raise GitCleanBranchesError(f"Failed to list merged remote branches against '{base_ref}'.")
    branches = _parse_branch_list(proc.stdout)
    return [b for b in branches if b.startswith(f"{ctx.remote}/")]


def _branch_committer_unix_by_ref(ctx: RepoContext, *, ref_prefix: str) -> dict[str, int]:
    proc = _git(
        [
            "for-each-ref",
            "--format=%(refname:short)\t%(committerdate:unix)",
            ref_prefix,
        ],
        cwd=ctx.cwd,
        check=False,
    )
    if proc.returncode != 0:
        raise GitCleanBranchesError(f"Failed to read committer dates for refs under '{ref_prefix}'.")
    out: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        raw = line.strip()
        if not raw:
            continue
        name, _, ts = raw.partition("\t")
        if not name or not ts:
            continue
        try:
            out[name] = int(ts)
        except ValueError:
            continue
    return out


def _stale_local(ctx: RepoContext, *, days: int) -> list[str]:
    cutoff = int(time.time()) - (days * 24 * 60 * 60)
    by_name = _branch_committer_unix_by_ref(ctx, ref_prefix="refs/heads")
    return sorted([name for name, ts in by_name.items() if ts <= cutoff])


def _stale_remote(ctx: RepoContext, *, days: int) -> list[str]:
    if ctx.remote is None:
        return []
    cutoff = int(time.time()) - (days * 24 * 60 * 60)
    by_name = _branch_committer_unix_by_ref(ctx, ref_prefix=f"refs/remotes/{ctx.remote}")
    branches = []
    for name, ts in by_name.items():
        if name == f"{ctx.remote}/HEAD":
            continue
        if ts <= cutoff:
            branches.append(name)
    return sorted(branches)


def _filter_candidates(
    branches: list[str],
    *,
    base_short: str,
    current_branch: str | None,
    protected_patterns: list[str],
    remote_prefix: str | None = None,
) -> list[str]:
    filtered: list[str] = []
    for b in branches:
        short = b
        if remote_prefix and short.startswith(remote_prefix):
            short = short[len(remote_prefix) :]

        if short == base_short:
            continue
        if current_branch and short == current_branch:
            continue
        if _is_protected(short, protected_patterns) or _is_protected(b, protected_patterns):
            continue
        filtered.append(b)
    return sorted(dict.fromkeys(filtered))


def _plan_cleanup(
    ctx: RepoContext,
    *,
    base_ref: str,
    stale_days: int | None,
    include_remote: bool,
) -> CleanupPlan:
    protected_patterns = _read_protected_patterns(ctx)
    base_short = base_ref.split("/", 1)[1] if ctx.remote and base_ref.startswith(f"{ctx.remote}/") else base_ref

    merged_local = _filter_candidates(
        _merged_local(ctx, base_ref=base_ref),
        base_short=base_short,
        current_branch=ctx.current_branch,
        protected_patterns=protected_patterns,
    )
    merged_remote_raw = _merged_remote(ctx, base_ref=base_ref) if include_remote else []
    merged_remote = _filter_candidates(
        merged_remote_raw,
        base_short=base_short,
        current_branch=ctx.current_branch,
        protected_patterns=protected_patterns,
        remote_prefix=f"{ctx.remote}/" if ctx.remote else None,
    )

    stale_local: list[str] = []
    stale_remote: list[str] = []
    if stale_days is not None:
        stale_local = _filter_candidates(
            _stale_local(ctx, days=stale_days),
            base_short=base_short,
            current_branch=ctx.current_branch,
            protected_patterns=protected_patterns,
        )
        stale_remote_raw = _stale_remote(ctx, days=stale_days) if include_remote else []
        stale_remote = _filter_candidates(
            stale_remote_raw,
            base_short=base_short,
            current_branch=ctx.current_branch,
            protected_patterns=protected_patterns,
            remote_prefix=f"{ctx.remote}/" if ctx.remote else None,
        )

    return CleanupPlan(
        merged_local=merged_local,
        merged_remote=merged_remote,
        stale_local=stale_local,
        stale_remote=stale_remote,
    )


def _print_plan(ctx: RepoContext, *, base_ref: str, stale_days: int | None, include_remote: bool, plan: CleanupPlan) -> None:
    protected_patterns = _read_protected_patterns(ctx)
    print(f"Base ref: {base_ref}")
    print(f"Current branch: {ctx.current_branch or '(detached)'}")
    if include_remote:
        if ctx.remote is None:
            print("Remote: (none)")
        else:
            print(f"Remote: {ctx.remote}")
    if stale_days is not None:
        print(f"Stale cutoff: {stale_days} day(s)")
    if protected_patterns:
        print("Protected patterns:")
        for pat in protected_patterns:
            print(f"  - {pat}")
    print()

    def _print_section(title: str, branches: list[str]) -> None:
        print(title)
        if not branches:
            print("  (none)")
            return
        for b in branches:
            print(f"  - {b}")

    _print_section("Merged local branches to delete:", plan.merged_local)
    if include_remote:
        _print_section("Merged remote branches to delete:", plan.merged_remote)
    if stale_days is not None:
        stale_local_title = "Stale local branches to delete:"
        stale_remote_title = "Stale remote branches to delete:"
    elif plan.stale_local or plan.stale_remote:
        stale_local_title = "Explicit local branches to delete:"
        stale_remote_title = "Explicit remote branches to delete:"
    else:
        return

    _print_section(stale_local_title, plan.stale_local)
    if include_remote:
        _print_section(stale_remote_title, plan.stale_remote)


def _delete_local(ctx: RepoContext, branch: str, *, force: bool) -> tuple[bool, str]:
    args = ["branch", "-D" if force else "-d", branch]
    proc = _git(args, cwd=ctx.cwd, check=False)
    ok = proc.returncode == 0
    msg = (proc.stdout or proc.stderr).strip()
    return ok, msg


def _delete_remote(ctx: RepoContext, remote_branch: str) -> tuple[bool, str]:
    if ctx.remote is None:
        return False, "No remote configured."
    if not remote_branch.startswith(f"{ctx.remote}/"):
        return False, f"Not a {ctx.remote}/ branch: {remote_branch}"
    name = remote_branch.split("/", 1)[1]
    proc = _git(["push", ctx.remote, "--delete", name], cwd=ctx.cwd, check=False)
    ok = proc.returncode == 0
    msg = (proc.stdout or proc.stderr).strip()
    return ok, msg


def _unique_in_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _execute_plan(ctx: RepoContext, plan: CleanupPlan, *, include_remote: bool, force: bool) -> int:
    local_targets = _unique_in_order([*plan.merged_local, *plan.stale_local])
    remote_targets = _unique_in_order([*plan.merged_remote, *plan.stale_remote]) if include_remote else []

    failures = 0
    for b in local_targets:
        ok, msg = _delete_local(ctx, b, force=force)
        if ok:
            print(f"[OK] Deleted local branch: {b}")
        else:
            failures += 1
            print(f"[ERR] Failed to delete local branch: {b}", file=sys.stderr)
        if msg:
            print(f"      {msg}")

    for b in remote_targets:
        ok, msg = _delete_remote(ctx, b)
        if ok:
            print(f"[OK] Deleted remote branch: {b}")
        else:
            failures += 1
            print(f"[ERR] Failed to delete remote branch: {b}", file=sys.stderr)
        if msg:
            print(f"      {msg}")

    if failures:
        print(f"\nCompleted with {failures} failure(s).", file=sys.stderr)
        return 2
    print("\nCompleted successfully.")
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Safely find and clean up merged or stale Git branches (dry-run by default unless --yes).",
    )
    p.add_argument("--base", help="Base branch/ref for merged detection (defaults to main/master/HEAD).")
    p.add_argument("--stale", type=int, help="Also consider branches with no commits for N days.")
    p.add_argument("--remote", action="store_true", help="Also consider remote branches (origin by default).")
    p.add_argument("--force", action="store_true", help="Use -D for local deletions (even if unmerged).")
    p.add_argument("--dry-run", action="store_true", help="Preview only (never delete).")
    p.add_argument("--yes", action="store_true", help="Apply deletions (required to actually delete).")
    p.add_argument("branches", nargs="*", help="Optional explicit local branches to delete (use with --force).")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    cwd = Path.cwd()
    _ensure_git_repo(cwd)

    remote = _resolve_remote(cwd) if args.remote else None
    ctx = RepoContext(cwd=cwd, current_branch=_current_branch(cwd), remote=remote)

    base_ref = args.base or _default_base_ref(ctx)
    if args.remote and remote is None:
        print("[WARN] --remote was set but no Git remotes were found; remote cleanup will be skipped.", file=sys.stderr)

    effective_dry_run = args.dry_run or not args.yes

    if args.branches:
        plan = CleanupPlan(
            merged_local=[],
            merged_remote=[],
            stale_local=sorted(dict.fromkeys(args.branches)),
            stale_remote=[],
        )
        _print_plan(ctx, base_ref=base_ref, stale_days=None, include_remote=False, plan=plan)
        if effective_dry_run:
            print("\nDry-run: no deletions performed. Re-run with --yes to apply.")
            return 0
        if not args.force:
            raise GitCleanBranchesError("Explicit branch deletion requires --force (safety guard).")
        return _execute_plan(ctx, plan, include_remote=False, force=True)

    if args.stale is not None and args.stale < 0:
        raise GitCleanBranchesError("--stale must be a non-negative integer.")

    if args.remote:
        _try_fetch_all_prune(ctx)

    plan = _plan_cleanup(ctx, base_ref=base_ref, stale_days=args.stale, include_remote=args.remote)
    _print_plan(ctx, base_ref=base_ref, stale_days=args.stale, include_remote=args.remote, plan=plan)

    if effective_dry_run:
        print("\nDry-run: no deletions performed. Re-run with --yes to apply.")
        return 0

    return _execute_plan(ctx, plan, include_remote=args.remote, force=args.force)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except GitCleanBranchesError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        raise SystemExit(1)
