"""BIOS profiles: saved BIOS settings, checked against the BIOS's own attribute registry, applied by
Configure BIOS (only what differs is written, one reboot, read back).

A profile is captured from a server (its current settings, the ones you keep), edited in GroundZero (from
the registry: each setting's allowed values and bounds), or imported from a file (a plain
``{attribute: value}`` map, or a Dell Server Configuration Profile's BIOS component). BIOS passwords are
never kept.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from groundzero.redfish.bios import BiosChange
from groundzero.redfish.bios_registry import BiosRegistry


class BiosProfileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    registry: str = Field(description="The registry the profile is checked against (GET /bios-registries)")
    attributes: dict[str, str | int | bool] = Field(
        min_length=1, description="BIOS attribute → value; only these are written, the rest are left alone"
    )


class BiosProfile(BiosProfileWrite):
    id: str
    model: str | None = Field(default=None, description="The server model the registry came from")
    source: str = Field(default="manual", description="manual, imported, or captured from <host>")
    created_at: datetime
    updated_at: datetime


class BiosCapture(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    attributes: list[str] | None = Field(
        default=None,
        description="Which settings to keep; default: every settable choice (lists, numbers, on/off), "
        "leaving out free text such as asset tags and iSCSI names, which belong to one server",
    )


class BiosImport(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    registry: str = Field(description="The registry to check the file against")
    content: str = Field(
        description='The file: {attribute: value}, {"Attributes": {...}}, or a Dell SCP JSON'
    )


class BiosPlan(BaseModel):
    """What Configure BIOS would write now, judged from the latest inventory."""

    changes: list[BiosChange]
    unsupported: list[str] = Field(default_factory=list)
    inventory_at: datetime


class RegistryInfo(BaseModel):
    """A cached registry, as the editor reads it: settable attributes only, in BIOS setup order."""

    key: str = Field(description="Cache key: <model>|<registry id>")
    id: str
    model: str | None
    attributes: list[dict[str, Any]]


def capture_defaults(registry: BiosRegistry, current: dict[str, Any]) -> list[str]:
    """The settings a capture keeps unless told otherwise: settable choices the server reports."""
    return [
        name
        for name, attr in registry.attributes.items()
        if attr.settable
        and attr.type in ("Enumeration", "Integer", "Boolean")
        and current.get(name) is not None
    ]


def parse_import(content: str, registry: BiosRegistry) -> dict[str, Any]:
    """Read a profile file: a flat map, an {"Attributes": ...} body, or a Dell SCP export (BIOS.Setup.1-1).

    SCP values are all strings, so integers and booleans are converted using the registry's types.
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not JSON: {exc.msg} (line {exc.lineno})") from exc
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object")
    scp = data.get("SystemConfiguration")
    if isinstance(scp, dict):
        bios = next(
            (c for c in scp.get("Components") or [] if str(c.get("FQDD", "")).startswith("BIOS.Setup")), None
        )
        if bios is None:
            raise ValueError("The Server Configuration Profile has no BIOS component (BIOS.Setup.1-1)")
        raw = {
            a["Name"]: a.get("Value")
            for a in bios.get("Attributes") or []
            if a.get("Name") and "#" not in a["Name"]  # "#Comment" rows are documentation
        }
    elif isinstance(data.get("Attributes"), dict):
        raw = data["Attributes"]
    else:
        raw = data
    return {name: _typed(registry, name, value) for name, value in raw.items() if value is not None}


def _typed(registry: BiosRegistry, name: str, value: Any) -> Any:
    attr = registry.attributes.get(name)
    if attr is None or not isinstance(value, str):
        return value
    if attr.type == "Integer":
        try:
            return int(value)
        except ValueError:
            return value
    if attr.type == "Boolean":
        return {"true": True, "false": False}.get(value.lower(), value)
    return value
