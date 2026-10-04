"""OS plugin registry."""

from __future__ import annotations

from groundzero.osconfig.base import CaptureResult, OsPlugin
from groundzero.osconfig.esxi import EsxiPlugin, OsConfigError
from groundzero.osconfig.holodeck import HolodeckPlugin

PLUGINS: dict[str, type[OsPlugin]] = {EsxiPlugin.family: EsxiPlugin, HolodeckPlugin.family: HolodeckPlugin}


def plugin_for(family: str) -> type[OsPlugin]:
    try:
        return PLUGINS[family]
    except KeyError:
        raise OsConfigError(f"Unknown OS family '{family}'; choose from {sorted(PLUGINS)}") from None


__all__ = [
    "PLUGINS",
    "CaptureResult",
    "EsxiPlugin",
    "HolodeckPlugin",
    "OsConfigError",
    "OsPlugin",
    "plugin_for",
]
