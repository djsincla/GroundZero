"""Appliance profiles: saved values for an OVA (its properties, network mapping and passwords).

A profile belongs to a product (the OVA's ``<Product>``), so it keeps working across versions of that
appliance. Values are checked against the descriptor of the OVA they are used with; passwords are stored
sealed, separately from the other values, and never returned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, SecretStr

from groundzero.ova.descriptor import DescriptorError, OvfDescriptor

_INTEGER_TYPES = {"int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64"}


class ApplianceProfileWrite(BaseModel):
    """Create or replace a profile. ``values`` and ``secrets`` use OVF property keys (bare or qualified)."""

    name: str = Field(min_length=1, max_length=80)
    image_id: str = Field(description="An OVA in the image repository; the profile is for its product")
    values: dict[str, Any] = Field(default_factory=dict, description="Property values (not passwords)")
    secrets: dict[str, SecretStr] | None = Field(
        default=None, description="Password properties. Write-only; on update, omitted ones are kept."
    )
    networks: dict[str, str] = Field(
        default_factory=dict, description="OVF network name → port group on the host"
    )

    def secret_values(self) -> dict[str, str]:
        return {k: v.get_secret_value() for k, v in (self.secrets or {}).items() if v.get_secret_value()}


class ApplianceProfile(BaseModel):
    id: str
    name: str
    product: str = Field(description="The OVA product this profile is for, e.g. HoloRouter")
    image_id: str | None = Field(default=None, description="The OVA it was made with (may since be removed)")
    values: dict[str, Any]
    networks: dict[str, str]
    secrets_set: list[str] = Field(
        default_factory=list, description="Password properties stored (never values)"
    )
    source: str = Field(description='"manual" or "captured from <vm>"')
    created_at: datetime
    updated_at: datetime


def check_values(
    desc: OvfDescriptor, values: dict[str, Any], secrets: dict[str, str], networks: dict[str, str]
) -> tuple[dict[str, Any], dict[str, str], list[dict[str, object]]]:
    """Qualified values and secrets, plus field errors (``loc`` = [where, key]) for what doesn't fit."""
    errors: list[dict[str, object]] = []
    by_key = {p.qualified_key: p for p in desc.properties}

    def qualify(where: str, given: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in given.items():
            try:
                (qualified,) = desc.qualify({key: value})
            except DescriptorError as exc:
                errors.append({"loc": [where, key], "msg": str(exc), "type": "unknown_property"})
                continue
            out[qualified] = value
        return out

    clean = qualify("values", values)
    sealed = qualify("secrets", secrets)
    for key in list(clean):
        prop = by_key[key]
        value = clean[key]
        if prop.password:
            errors.append(
                {"loc": ["values", key], "msg": "is a password: send it in secrets", "type": "secret"}
            )
            del clean[key]
            continue
        if prop.type == "boolean":
            if isinstance(value, str) and value.lower() in ("true", "false"):
                value = value.lower() == "true"
            if not isinstance(value, bool):
                errors.append({"loc": ["values", key], "msg": "must be true or false", "type": "bool_type"})
                continue
        elif prop.type in _INTEGER_TYPES:
            try:
                value = int(value)
            except (TypeError, ValueError):
                errors.append({"loc": ["values", key], "msg": "must be a whole number", "type": "int_type"})
                continue
        elif value is not None:
            value = str(value)
        clean[key] = value
        errors.extend(_string_errors("values", key, prop.choices, prop.min_length, prop.max_length, value))
    for key, value in sealed.items():
        prop = by_key[key]
        if not prop.password:
            errors.append(
                {"loc": ["secrets", key], "msg": "is not a password property", "type": "not_secret"}
            )
            continue
        errors.extend(_string_errors("secrets", key, None, prop.min_length, prop.max_length, value))
    declared = {n.name for n in desc.networks}
    for name in networks:
        if name not in declared:
            errors.append(
                {"loc": ["networks", name], "msg": f"the OVA has no network {name!r}", "type": "network"}
            )
    return clean, sealed, errors


def _string_errors(
    where: str, key: str, choices: list[str] | None, min_len: int | None, max_len: int | None, value: Any
) -> list[dict[str, object]]:
    if not isinstance(value, str) or value == "":
        return []
    if choices and value not in choices:
        return [{"loc": [where, key], "msg": f"must be one of {choices}", "type": "enum"}]
    if min_len is not None and len(value) < min_len:
        return [{"loc": [where, key], "msg": f"must be at least {min_len} characters", "type": "too_short"}]
    if max_len is not None and len(value) > max_len:
        return [{"loc": [where, key], "msg": f"must be at most {max_len} characters", "type": "too_long"}]
    return []
