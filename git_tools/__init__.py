"""Git Tools package and installed distribution version."""

from importlib.metadata import PackageNotFoundError, version

try:
    # pyproject.toml supplies this metadata when the tool is installed.
    __version__ = version("git-tools")
except PackageNotFoundError:
    # The stdlib-only bump engine also runs from uninstalled checkouts in CI.
    __version__ = "unknown"

__all__ = ["__version__"]
