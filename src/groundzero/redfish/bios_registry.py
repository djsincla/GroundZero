"""The BIOS attribute registry: what each BIOS setting is, its type, and the values it accepts.

The Bios resource names its registry ("AttributeRegistry": "BiosAttributeRegistry.v1_0_3"). The registry
is found through /redfish/v1/Registries: the member with that id lists where the registry file is
(``Location[].Uri``). Its ``RegistryEntries.Attributes`` describe every attribute: display name, type
(Enumeration, String, Integer, Boolean, Password), allowed values, bounds, read-only, hidden, and the
menu it sits in. That is what BIOS profiles are checked against and how the editor is built.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from groundzero.redfish.client import RedfishClient
from groundzero.redfish.errors import RedfishError

AttributeType = Literal["Enumeration", "String", "Integer", "Boolean", "Password"]


class BiosValue(BaseModel):
    name: str
    display: str | None = None


class BiosAttribute(BaseModel):
    name: str
    display: str | None = None
    help: str | None = None
    type: AttributeType
    values: list[BiosValue] = Field(default_factory=list, description="Allowed values (Enumeration)")
    read_only: bool = False
    hidden: bool = False
    menu: str | None = Field(
        default=None, description="Where it sits in the BIOS setup, e.g. Processor Settings"
    )
    order: int = Field(default=0, description="The BIOS setup's own display order")
    lower: int | None = None
    upper: int | None = None
    min_length: int | None = None
    max_length: int | None = None
    default: str | int | bool | None = None

    @property
    def settable(self) -> bool:
        return not self.read_only and not self.hidden and self.type != "Password"


class BiosRegistry(BaseModel):
    id: str = Field(description="e.g. BiosAttributeRegistry.v1_0_3")
    language: str | None = None
    attributes: dict[str, BiosAttribute]

    def check(self, settings: dict[str, Any]) -> list[tuple[str, str, str]]:
        """Problems with a set of attribute values: (attribute, message, error type)."""
        problems = []
        for name, value in settings.items():
            attr = self.attributes.get(name)
            if attr is None:
                problems.append((name, "Not a setting this BIOS has", "unknown_attribute"))
            elif attr.type == "Password":
                problems.append((name, "BIOS passwords aren't kept in a profile", "secret"))
            elif attr.read_only:
                problems.append(
                    (name, "Read-only: the BIOS reports it but won't take a new value", "read_only")
                )
            elif attr.type == "Enumeration":
                allowed = [v.name for v in attr.values]
                if value not in allowed:
                    problems.append((name, f"Must be one of {', '.join(allowed)}", "enum"))
            elif attr.type == "Integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    problems.append((name, "Must be a whole number", "int_type"))
                elif (attr.lower is not None and value < attr.lower) or (
                    attr.upper is not None and value > attr.upper
                ):
                    problems.append((name, f"Must be between {attr.lower} and {attr.upper}", "range"))
            elif attr.type == "Boolean":
                if not isinstance(value, bool):
                    problems.append((name, "Must be true or false", "bool_type"))
            elif not isinstance(value, str):
                problems.append((name, "Must be text", "string_type"))
            elif (attr.min_length is not None and len(value) < attr.min_length) or (
                attr.max_length is not None and len(value) > attr.max_length
            ):
                problems.append((name, f"Must be {attr.min_length}-{attr.max_length} characters", "length"))
        return problems


def parse_registry(body: dict[str, Any]) -> BiosRegistry:
    registry = body.get("RegistryEntries") or {}
    entries = registry.get("Attributes") or []
    menus = {
        m.get("MenuName"): m.get("DisplayName") for m in registry.get("Menus") or [] if m.get("MenuName")
    }
    attributes = {}
    for raw in entries:
        name = raw.get("AttributeName")
        kind = raw.get("Type")
        if not name or kind not in ("Enumeration", "String", "Integer", "Boolean", "Password"):
            continue
        attributes[name] = BiosAttribute(
            name=name,
            display=raw.get("DisplayName"),
            help=raw.get("HelpText"),
            type=kind,
            values=[
                BiosValue(name=str(v["ValueName"]), display=v.get("ValueDisplayName"))
                for v in raw.get("Value") or []
                if "ValueName" in v
            ],
            read_only=bool(raw.get("ReadOnly") or raw.get("Immutable")),
            hidden=bool(raw.get("Hidden")),
            menu=_menu(raw.get("MenuPath"), menus),
            order=int(raw.get("DisplayOrder") or 0),
            lower=raw.get("LowerBound"),
            upper=raw.get("UpperBound"),
            min_length=raw.get("MinLength"),
            max_length=raw.get("MaxLength"),
            default=raw.get("DefaultValue"),
        )
    registry_id = str(body.get("Id") or body.get("RegistryVersion") or "")
    return BiosRegistry(id=registry_id, language=body.get("Language"), attributes=attributes)


def _menu(path: Any, menus: dict[str, str]) -> str | None:
    """'./ProcSettingsRef' → 'Processor Settings' (the menu's display name), else the bare menu name."""
    if not isinstance(path, str):
        return None
    parts = [p for p in path.strip("./").split("/") if p]
    return " / ".join(menus.get(p) or p.removesuffix("Ref") for p in parts) or None


def _base(registry_id: str) -> str:
    """BiosAttributeRegistry.v1_0_3 → BiosAttributeRegistry (iDRAC lists v1_0_0; its Bios names v1_0_3)."""
    return re.split(r"\.v?\d|\d+\.\d", registry_id, maxsplit=1)[0]


async def fetch_registry(client: RedfishClient, bios: dict[str, Any]) -> BiosRegistry | None:
    """Find and read the registry the Bios resource names; None if this BMC doesn't publish one.

    The Registries member whose id has the same base name says where the file is; failing that, Dell's
    well-known Bios/BiosRegistry. Only that member is read, not every registry the BMC lists.
    """
    registry_id = bios.get("AttributeRegistry")
    if not registry_id:
        return None
    uris: list[str] = []
    try:
        collection = await client.get_json("/redfish/v1/Registries")
        links = [m["@odata.id"] for m in collection.get("Members") or [] if "@odata.id" in m]
        wanted = [link for link in links if _base(link.rsplit("/", 1)[-1]) == _base(registry_id)]
        for link in wanted[:1]:
            file = await client.get_json(link)
            locations = file.get("Location") or []
            uris += [loc["Uri"] for loc in locations if loc.get("Uri") and loc.get("Language", "en") == "en"]
            uris += [loc["Uri"] for loc in locations if loc.get("Uri")]
    except RedfishError:
        pass
    if bios.get("@odata.id"):
        uris.append(f"{bios['@odata.id']}/BiosRegistry")
    for uri in dict.fromkeys(uris):
        try:
            body = await client.get_json(uri)
        except RedfishError:
            continue
        if (body.get("RegistryEntries") or {}).get("Attributes"):
            return parse_registry(body)
    return None
