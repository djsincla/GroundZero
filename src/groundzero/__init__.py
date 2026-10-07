"""GroundZero — API-first bare metal → OS → VMware Holodeck provisioning."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("groundzero")  # single source of truth: pyproject.toml
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
