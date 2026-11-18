"""Atomic, non-clobbering output for finished generated documents and messages."""

from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
from secrets import token_hex
from tempfile import TemporaryDirectory


DRAFT_NAMES = {"pr": "PR", "issue": "ISSUE", "both": "ISSUEPR", "commit": "COMMIT"}
_DIRECTORY_FD_IO = {os.open, os.mkdir, os.stat, os.unlink, os.rmdir, os.link}.issubset(os.supports_dir_fd)


def _git_admin_directories(directory: Path, *search_directories: Path) -> set[Path]:
    """Recognize Git metadata layouts and worktrees; relative Git environment paths use the invocation directory."""
    protected = {(directory / os.environ[key]).resolve() for key in ("GIT_DIR", "GIT_COMMON_DIR") if os.environ.get(key)}
    for search in (directory, *search_directories):
        for root in (search, *search.parents):
            # Bare repositories and separately named administrative directories have no child .git marker.
            if (root / "HEAD").is_file() and (root / "objects").is_dir() and ((root / "refs").is_dir() or (root / "reftable").is_dir()):
                protected.add(root.resolve())
            marker = root / ".git"
            if marker.is_dir():
                protected.add(marker.resolve())
            elif marker.is_file():
                text = marker.read_text(encoding="utf-8").strip()
                if text.startswith("gitdir: "):
                    protected.add((root / text.removeprefix("gitdir: ")).resolve())
    for gitdir in tuple(protected):
        common = gitdir / "commondir"
        if common.is_file():
            protected.add((gitdir / common.read_text(encoding="utf-8").strip()).resolve())
    return protected


def _reject_git_admin_path(path: Path, directory: Path, *, is_directory: bool = False) -> None:
    """Inspect current parent ancestry without ever following an output-file symlink."""
    message = "Output cannot write inside Git administrative directories."
    canonical = path.resolve() if is_directory else path.parent.resolve() / path.name
    if ".git" in path.parts or ".git" in canonical.parts:
        raise PermissionError(message)
    ancestors = (path, *path.parents) if is_directory else path.parents
    search = canonical if is_directory else canonical.parent
    for admin in _git_admin_directories(directory, search):
        if path.is_relative_to(admin) or canonical.is_relative_to(admin):
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


def _directory_identity(stat: os.stat_result) -> tuple[int, int]:
    return stat.st_dev, stat.st_ino


def _check_parent(parent: Path, identity: tuple[int, int], directory: Path) -> None:
    _reject_git_admin_path(parent, directory, is_directory=True)
    if _directory_identity(parent.stat()) != identity:
        raise OSError("Output directory changed while saving; inspect the original directory before retrying.")


@contextmanager
def _draft_staging(parent: Path, directory: Path):
    """Keep private staging and publication anchored where directory-relative I/O is supported."""
    identity = _directory_identity(parent.stat())
    _check_parent(parent, identity, directory)
    if not _DIRECTORY_FD_IO:
        # Retain portable path-based publication, with fresh canonical and identity checks.
        with TemporaryDirectory(prefix=".git-tools-draft-", dir=parent, ignore_cleanup_errors=True) as pending:
            _check_parent(parent, identity, directory)
            yield Path(pending) / "draft.md", None, None, identity
        return

    # Search-only handles avoid requiring directory-read permission just to create a draft.
    flags = getattr(os, "O_PATH", getattr(os, "O_SEARCH", os.O_RDONLY)) | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_fd = os.open(parent, flags)
    staging_fd = None
    staging_name = None
    try:
        if _directory_identity(os.fstat(parent_fd)) != identity:
            raise OSError("Output directory changed before saving; retry with a stable directory.")
        _check_parent(parent, identity, directory)
        while True:
            name = ".git-tools-draft-" + token_hex(12)
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                continue
            staging_name = name
            break
        staging_fd = os.open(staging_name, flags, dir_fd=parent_fd)
        _check_parent(parent, identity, directory)
        yield Path("draft.md"), staging_fd, parent_fd, identity
    finally:
        # Only our private stage is removed. Never unlink or roll back a public destination.
        if staging_fd is not None:
            try:
                os.unlink("draft.md", dir_fd=staging_fd)
            except OSError:
                pass
            finally:
                os.close(staging_fd)
        if staging_name is not None:
            try:
                os.rmdir(staging_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


def save_draft(content: str, generation_type: str, directory: Path, *, output_path: Path | None = None) -> Path:
    """Publish a complete UTF-8 draft; explicit names are exact, default names may gain suffixes."""
    if not content.strip():
        raise ValueError("Cannot save an empty draft")
    directory = directory.resolve()
    stem = DRAFT_NAMES[generation_type]
    target = output_path if output_path is not None else directory / f"{stem}.md"
    if not target.is_absolute():
        target = directory / target
    # A provider round trip can outlive the directory validated at preflight. Never resolve the final leaf.
    target = target.parent.resolve() / target.name
    _reject_git_admin_path(target, directory)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    with _draft_staging(target.parent, directory) as (staged, staging_fd, parent_fd, identity):
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=staging_fd)
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
            _check_parent(target.parent, identity, directory)
            try:
                os.link(staged, path.name if parent_fd is not None else path, src_dir_fd=staging_fd, dst_dir_fd=parent_fd)
            except FileExistsError:
                if output_path is not None:
                    raise
                attempt += 1
                continue
            _check_parent(target.parent, identity, directory)
            return path
