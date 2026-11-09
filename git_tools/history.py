"""Small, read-only views of locally available Git history."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import re
import subprocess


_PSEUDO_REFS = frozenset({
    "HEAD", "@", "FETCH_HEAD", "ORIG_HEAD", "MERGE_HEAD", "REBASE_HEAD",
    "CHERRY_PICK_HEAD", "REVERT_HEAD", "AUTO_MERGE", "BISECT_HEAD",
})


class HistoryError(RuntimeError):
    """Git history could not be read from the requested repository or ref."""


class LogView(str, Enum):
    BRANCH = "branch"
    COMPARE = "compare"
    ALL = "all"


@dataclass(frozen=True)
class HistorySnapshot:
    branch: str
    head: str | None
    base_ref: str | None
    base_sha: str | None
    ahead: int | None
    behind: int | None
    local_branches: int
    remote_branches: int


def _git(*args: str, cwd: str | Path | None, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    try:
        result = subprocess.run(
            ["git", "--no-pager", *args], cwd=cwd, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except FileNotFoundError as exc:
        raise HistoryError("Cannot run Git: ensure Git is installed and the working directory exists.") from exc
    except subprocess.TimeoutExpired as exc:
        raise HistoryError("Git history lookup timed out; try a smaller history view.") from exc
    except OSError as exc:
        raise HistoryError(f"Cannot run Git: {exc}") from exc
    if result.returncode not in ok:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise HistoryError(f"Git {args[0]} failed: {detail}")
    return result


def _commit(ref: str, *, cwd: str | Path | None) -> str | None:
    result = _git("rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{commit}}", cwd=cwd, ok=(0, 1))
    return result.stdout.strip() if result.returncode == 0 else None


def _base(base: str | None, *, cwd: str | Path | None) -> tuple[str | None, str | None]:
    if base is None:
        candidates = [("develop", "refs/heads/develop"), ("origin/develop", "refs/remotes/origin/develop")]
    else:
        if not base or "\0" in base or base.startswith("-"):
            raise HistoryError(f"Invalid base ref {base!r}; choose a local ref, tag, or commit.")
        # Preserve explicit Git revisions rather than guessing origin/HEAD~1, etc.
        if base.startswith("refs/") or base in _PSEUDO_REFS or re.search(r"[~^:]|@\{", base):
            candidates = [(base, base)]
        else:
            candidates = [
                (base, f"refs/heads/{base}"),
                (base, f"refs/remotes/{base}"),
                (f"origin/{base}", f"refs/remotes/origin/{base}"),
                (base, base),
            ]
    for label, ref in candidates:
        sha = _commit(ref, cwd=cwd)
        if sha is not None:
            return label, sha
    if base is not None:
        raise HistoryError(f"Cannot resolve base {base!r} to a local commit; choose an existing ref, tag, or commit (no fetch is performed).")
    return None, None


def history_snapshot(base: str | None = None, *, cwd: str | Path | None = None) -> HistorySnapshot:
    """Resolve HEAD/base once and count all reachable commits, without fetching."""
    _git("rev-parse", "--git-dir", cwd=cwd)
    symbolic = _git("symbolic-ref", "--quiet", "--short", "HEAD", cwd=cwd, ok=(0, 1))
    head = _commit("HEAD", cwd=cwd)
    if symbolic.returncode == 0:
        branch = symbolic.stdout.strip()
        if head is None:
            branch += " (unborn)"
    elif head is not None:
        branch = f"detached HEAD ({head[:7]})"
    else:
        raise HistoryError("Cannot resolve HEAD to a commit or an unborn branch.")

    refs = _git("for-each-ref", "--format=%(refname)\t%(symref)", "refs/heads/", "refs/remotes/", cwd=cwd)
    local_branches = remote_branches = 0
    for line in refs.stdout.splitlines():
        ref, _, target = line.partition("\t")
        if ref.startswith("refs/heads/"):
            local_branches += 1
        elif not (ref.endswith("/HEAD") and target):
            remote_branches += 1

    base_ref, base_sha = _base(base, cwd=cwd)
    ahead = behind = None
    if head is not None and base_sha is not None:
        counts = _git("rev-list", "--left-right", "--count", "--end-of-options", f"{base_sha}...{head}", "--", cwd=cwd)
        behind, ahead = map(int, counts.stdout.split())
    return HistorySnapshot(branch, head, base_ref, base_sha, ahead, behind, local_branches, remote_branches)


def render_log(
    snapshot: HistorySnapshot,
    view: LogView = LogView.BRANCH,
    *,
    limit: int = 30,
    first_parent: bool = True,
    cwd: str | Path | None = None,
) -> str:
    """Render a bounded graph; branch and compare views use the snapshot's SHAs."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("History limit must be a positive integer.")
    view = LogView(view)
    if view == LogView.COMPARE and snapshot.base_sha is None:
        raise HistoryError("Compare requires a base commit; select one with --base.")
    if view != LogView.ALL and snapshot.head is None:
        return ""

    args = ["log", "--graph", "--oneline", "--decorate=short", "--encoding=UTF-8", "--no-color", "--no-show-signature", "--no-notes", f"--max-count={limit}"]
    if first_parent:
        args.append("--first-parent")
    if view == LogView.ALL:
        args.extend(["--all", "--end-of-options"])
    elif view == LogView.COMPARE:
        args.extend(["--left-right", "--end-of-options", f"{snapshot.base_sha}...{snapshot.head}"])
    else:
        args.extend(["--end-of-options", snapshot.head])
    return _git(*args, "--", cwd=cwd).stdout.rstrip("\n")
