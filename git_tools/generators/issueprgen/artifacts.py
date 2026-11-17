"""Durable, non-clobbering Markdown drafts for issue/PR generation."""

from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory


DRAFT_NAMES = {"pr": "PR", "issue": "ISSUE", "both": "ISSUEPR"}


def save_draft(content: str, generation_type: str, directory: Path) -> Path:
    """Publish a complete UTF-8 draft without overwriting an existing entry."""
    if not content.strip():
        raise ValueError("Cannot save an empty draft")
    stem = DRAFT_NAMES[generation_type]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    # Failed writes are confined to a private directory, never a public draft name.
    with TemporaryDirectory(prefix=".git-tools-draft-", dir=directory, ignore_cleanup_errors=True) as pending:
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
            suffix = "" if attempt == 0 else f"-{timestamp}" + (f"-{attempt}" if attempt > 1 else "")
            path = directory / f"{stem}{suffix}.md"
            try:
                # A same-filesystem hard link publishes the finished inode atomically and cannot replace an occupied name.
                os.link(staged, path)
            except FileExistsError:
                attempt += 1
                continue
            return path
