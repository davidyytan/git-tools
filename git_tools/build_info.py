"""What is running: agent-cli's and agent-core's version, and for a git
checkout the tag and commit each is at.

Both are usually editable installs from their checkouts, so the version is
the checkout's pyproject.toml (an editable install's metadata keeps the one
it was installed with) and the tag and commit are read live from git. An
install from a wheel has the installed version; a machine without git, the
version alone.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

#: ``git describe --tags --long --dirty``: tag, commits since it, commit, dirty.
_DESCRIBED = re.compile(r"^(?P<tag>.+)-(?P<ahead>\d+)-g(?P<commit>[0-9a-f]+)(?P<dirty>-dirty)?$")


@dataclass(frozen=True)
class BuildInfo:
    name: str
    version: str
    tag: str | None = None
    ahead: int = 0  # commits since the tag
    commit: str | None = None
    dirty: bool = False  # uncommitted changes to tracked files

    def describe(self) -> str:
        """``0.2.0-alpha.2 · tag 0.2.0-alpha.2 · commit 3886106 (dirty)``."""
        parts = [self.version]
        if self.commit is not None:
            if self.tag is None:
                parts.append("no tag")
            else:
                parts.append(f"tag {self.tag}" + (f" +{self.ahead}" if self.ahead else ""))
            parts.append(f"commit {self.commit}" + (" (dirty)" if self.dirty else ""))
        return " · ".join(parts)


def _git(checkout: Path, *args: str) -> str | None:
    # The package's own checkout, not one an exported GIT_DIR points at.
    env = {key: value for key, value in os.environ.items() if key not in ("GIT_DIR", "GIT_WORK_TREE")}
    try:
        done = subprocess.run(
            ["git", "-C", str(checkout), *args], capture_output=True, text=True, timeout=2, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _checkout(name: str, module_file: str) -> tuple[Path, str] | None:
    """The source checkout ``name`` runs from, and the version its
    pyproject.toml gives: the folder above the package holds the project's
    own pyproject.toml (an installed wheel has none)."""
    root = Path(module_file).resolve().parent.parent
    try:
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(project, dict) or project.get("name") != name or "version" not in project:
        return None
    return root, str(project["version"])


def build_info(name: str, module_file: str) -> BuildInfo:
    """``name``'s version, and its tag and commit when ``module_file`` (the
    package's ``__init__``) lives in a git checkout of it."""
    # A source checkout's own version, even without git; else the installed one.
    found = _checkout(name, module_file)
    if found is None:
        try:
            return BuildInfo(name, version(name))
        except PackageNotFoundError:  # never stop the banner or --version
            return BuildInfo(name, "unknown")
    checkout, checkout_version = found
    info = BuildInfo(name, checkout_version)
    described = _git(checkout, "describe", "--tags", "--long", "--dirty")
    match = _DESCRIBED.match(described or "")
    if match:
        return BuildInfo(
            name, info.version, match["tag"], int(match["ahead"]), match["commit"], bool(match["dirty"]),
        )
    commit = _git(checkout, "rev-parse", "--short", "HEAD")
    if commit is None:
        return info
    status = _git(checkout, "status", "--porcelain", "--untracked-files=no")
    return BuildInfo(name, info.version, commit=commit, dirty=bool(status))


def running() -> tuple[BuildInfo, BuildInfo]:
    """agent-cli's and agent-core's build, in that order."""
    import agent_core

    import agent_cli

    return build_info("agent-cli", agent_cli.__file__), build_info("agent-core", agent_core.__file__)


def version_lines() -> list[str]:
    """One line per package, names aligned: ``agent-cli   0.2.0-alpha.2 · tag …``."""
    builds = running()
    width = max(len(build.name) for build in builds)
    return [f"{build.name:<{width}}  {build.describe()}" for build in builds]


__all__ = ["BuildInfo", "build_info", "running", "version_lines"]
