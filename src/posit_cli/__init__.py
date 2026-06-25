"""posit-cli: a single command-line interface for Posit Connect."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("posit-cli")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0+unknown"
