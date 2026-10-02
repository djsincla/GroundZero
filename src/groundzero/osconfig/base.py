"""OS plugins: everything OS-specific about configuring an install lives behind this interface.

A plugin declares two typed models (rendered as forms by the UI from their JSON schema):
- ``settings_model``: shared settings a *config set* stores (reusable across servers)
- ``host_values_model``: per-server values (hostname, IP, ...) remembered per host, overridable

Adding an OS (e.g. NSX bare-metal Edge) means adding a plugin; the API and UI pick it up as-is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel


class IsoMeta(BaseModel):
    version: str | None
    build: str | None


class CaptureResult(BaseModel):
    settings: dict[str, Any]
    host_values: dict[str, Any]


class OsPlugin(Protocol):
    family: ClassVar[str]
    title: ClassVar[str]
    install_supported: ClassVar[bool]
    settings_model: ClassVar[type[BaseModel]]
    host_values_model: ClassVar[type[BaseModel]]
    secret_fields: ClassVar[tuple[str, ...]]

    @staticmethod
    def detect_iso(path: Path) -> IsoMeta | None:
        """Version/build if this plugin's OS installer ISO, else None. Must not raise."""
        ...
