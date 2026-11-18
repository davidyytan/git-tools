"""Atomic, non-clobbering output for finished generated documents and messages."""

from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory


DRAFT_NAMES = {"pr": "PR", "issue": "ISSUE", "both": "ISSUEPR", "commit": "COMMIT"}


def _git_admin_directories(directory: Path) -> set[Path]:
    """Recognize ordinary and linked-worktree metadata without invoking Git."""
    protected = {(directory / os.environ[key]).resolve() for key in ("GIT_DIR", "GIT_COMMON_DIR") if os.environ.get(key)}
    for gitdir in tuple(protected):
        common = gitdir / "commondir"
        if common.is_file():
            protected.add((gitdir / common.read_text(encoding="utf-8").strip()).resolve())
    for root in (directory, *directory.parents):
        marker = root / ".git"
        if marker.is_dir():
            return protected | {marker.resolve()}
        if not marker.is_file():
            continue
        text = marker.read_text(encoding="utf-8").strip()
        if not text.startswith("gitdir: "):
            continue
        gitdir = (root / text.removeprefix("gitdir: ")).resolve()
        protected.add(gitdir)
        common = gitdir / "commondir"
        if common.is_file():
            protected.add((gitdir / common.read_text(encoding="utf-8").strip()).resolve())
        return protected
    return protected


def _reject_git_admin_path(path: Path, directory: Path, *, is_directory: bool = False) -> None:
    """Reject metadata aliases using directory identity without following an output file symlink."""
    message = "Output cannot write inside Git administrative directories."
    if ".git" in path.parts:
        raise PermissionError(message)
    ancestors = (path, *path.parents) if is_directory else path.parents
    for admin in _git_admin_directories(directory):
        if path.is_relative_to(admin):
            raise PermissionError(message)
        if admin.is_dir():
            for ancestor in ancestors:
                if ancestor.is_dir() and ancestor.samefile(admin):
                    raise PermissionError(message)


def resolve_output_path(output_path: str | Path | None, directory: Path, *, validate_default: bool = False) -> Path | None:
    """Preflight exact paths and known default delivery; publication still enforces no-clobber."""
    if output_path is None:
        if validate_default:
            try:
                _reject_git_admin_path(directory.resolve(), directory, is_directory=True)
            except (OSError, UnicodeError) as exc:
                raise ValueError(f"Cannot use default output directory {directory}: {exc}") from exc
        return None
    text = os.fspath(output_path)
    if not text:
        raise ValueError("--output requires a filename, not an empty path.")
    if text == "-":
        raise ValueError("--output - is not supported: choose a file path; stdout is a transcript, not raw output.")
    if any(text.endswith((separator, separator + ".")) for separator in (os.sep, os.altsep) if separator):
        raise ValueError("--output requires a file path, not directory syntax.")
    try:
        requested = Path(text).expanduser()
    except RuntimeError as exc:
        raise ValueError(f"Cannot resolve output path {text}: {exc}") from exc
    if not requested.name or requested.name in {".", ".."}:
        raise ValueError("--output requires a file path, not a directory.")
    target = requested if requested.is_absolute() else directory / requested
    # Resolve the parent only: resolving the final component would follow an occupied symlink.
    target = target.parent.resolve() / target.name
    try:
        if not target.parent.is_dir():
            raise ValueError(f"Output directory does not exist or is not a directory: {target.parent}")
        _reject_git_admin_path(target, directory)
        try:
            target.lstat()
        except FileNotFoundError:
            return target
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Cannot inspect output path {target}: {exc}") from exc
    raise ValueError(f"Output path already exists: {target}. Choose another path or omit --output for an automatic unique name.")


def save_draft(content: str, generation_type: str, directory: Path, *, output_path: Path | None = None) -> Path:
    """Publish a complete UTF-8 draft; explicit names are exact, default names may gain suffixes."""
    if not content.strip():
        raise ValueError("Cannot save an empty draft")
    directory = directory.resolve()
    stem = DRAFT_NAMES[generation_type]
    target = output_path if output_path is not None else directory / f"{stem}.md"
    if not target.is_absolute():
        target = directory / target
    _reject_git_admin_path(target, directory)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    with TemporaryDirectory(prefix=".git-tools-draft-", dir=target.parent, ignore_cleanup_errors=True) as pending:
        staged = Path(pending) / "draft.md"
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            draft = os.fdopen(fd, "w", encoding="utf-8", newline="")
        except BaseException:
            os.close(fd)
            raise
        with draft:
            draft.write(content)
            if not content.endswith("\n"):
                draft.write("\n")
            draft.flush()
            os.fsync(draft.fileno())
        attempt = 0
        while True:
            suffix = f"-{timestamp}" + (f"-{attempt}" if attempt > 1 else "")
            path = target if attempt == 0 else target.with_name(f"{target.stem}{suffix}{target.suffix}")
            try:
                os.link(staged, path)
            except FileExistsError:
                if output_path is not None:
                    raise
                attempt += 1
                continue
            return path
