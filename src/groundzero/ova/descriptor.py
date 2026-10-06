"""Read an OVA's OVF descriptor: what the appliance is and which inputs it takes.

Any OVA describes its inputs as properties in ``ProductSection``s. A property in
``<ProductSection ovf:class="network" ovf:instance="x">`` is read by the guest as ``network.<key>.x``
(the *qualified* key), not as the bare key: a live finding, the Holorouter ignored bare keys.
``descriptor_schema`` turns the user-configurable properties into a JSON Schema, so any OVA gets a
generated form; ``environment_values`` builds the full set of values the guest receives.
"""

from __future__ import annotations

import re
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

OVF = "http://schemas.dmtf.org/ovf/envelope/1"
RASD = "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData"
VMW = "http://www.vmware.com/schema/ovf"
MAX_DESCRIPTOR_BYTES = 8_000_000

_INTEGER_TYPES = {"int8", "uint8", "int16", "uint16", "int32", "uint32", "int64", "uint64"}


class DescriptorError(ValueError):
    error_type = "ova_invalid"


class OvfProperty(BaseModel):
    key: str = Field(description="As declared (ovf:key)")
    qualified_key: str = Field(description="What the guest reads: <class>.<key>[.<instance>]")
    type: str = "string"
    label: str | None = None
    description: str | None = None
    category: str | None = None
    default: str | None = None
    password: bool = False
    user_configurable: bool = False
    choices: list[str] | None = Field(default=None, description="ValueMap{...}: the only accepted values")
    min_length: int | None = None
    max_length: int | None = None


class OvfNetwork(BaseModel):
    name: str
    description: str | None = None


class DeploymentOption(BaseModel):
    id: str
    label: str | None = None
    default: bool = False


class OvfDescriptor(BaseModel):
    product: str | None = None
    vendor: str | None = None
    version: str | None = None
    full_version: str | None = None
    transport: list[str] = Field(default_factory=list, description="e.g. com.vmware.guestInfo, iso")
    properties: list[OvfProperty] = Field(default_factory=list)
    networks: list[OvfNetwork] = Field(default_factory=list)
    cpus: int | None = None
    memory_mb: int | None = None
    disk_gb: float | None = None
    deployment_options: list[DeploymentOption] = Field(default_factory=list)
    has_eula: bool = False

    def qualify(self, values: dict[str, Any]) -> dict[str, Any]:
        """Bare or qualified keys → qualified keys. Keys the OVA does not declare are an error."""
        known: dict[str, str] = {}
        for p in self.properties:
            known.setdefault(p.key, p.qualified_key)
            known[p.qualified_key] = p.qualified_key
        unknown = sorted(k for k in values if k not in known)
        if unknown:
            raise DescriptorError(
                f"The OVA declares no propert{'y' if len(unknown) == 1 else 'ies'} {', '.join(unknown)}"
            )
        return {known[k]: v for k, v in values.items()}


def _tag(el: ET.Element) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _attr(el: ET.Element, name: str) -> str | None:
    return el.get(f"{{{OVF}}}{name}") or el.get(name)


def _text(el: ET.Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    text = " ".join(el.text.split())
    return text or None


def _child(el: ET.Element, name: str) -> ET.Element | None:
    return next((c for c in el if _tag(c) == name), None)


def _qualifiers(raw: str | None) -> tuple[list[str] | None, int | None, int | None]:
    """ValueMap{"a","b"}, MinLen(15), MaxLen(65535)."""
    if not raw:
        return None, None, None
    choices = None
    if m := re.search(r"ValueMap\{(.*?)\}", raw):
        choices = [c.strip().strip('"') for c in m.group(1).split(",") if c.strip()]
    min_len = int(m.group(1)) if (m := re.search(r"MinLen\((\d+)\)", raw)) else None
    max_len = int(m.group(1)) if (m := re.search(r"MaxLen\((\d+)\)", raw)) else None
    return choices, min_len, max_len


def parse_descriptor(xml: str) -> OvfDescriptor:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DescriptorError(f"The OVF descriptor is not valid XML: {exc}") from exc
    if _tag(root) != "Envelope":
        raise DescriptorError("Not an OVF descriptor (no Envelope)")
    system = next((el for el in root.iter() if _tag(el) == "VirtualSystem"), root)
    desc = OvfDescriptor(has_eula=any(_tag(el) == "EulaSection" for el in root.iter()))

    for section in (el for el in system.iter() if _tag(el) == "ProductSection"):
        cls, instance = _attr(section, "class"), _attr(section, "instance")
        if _child(section, "Product") is not None and desc.product is None:
            desc.product = _text(_child(section, "Product"))
            desc.vendor = _text(_child(section, "Vendor"))
            desc.version = _text(_child(section, "Version"))
            desc.full_version = _text(_child(section, "FullVersion"))
        category = None
        for el in section:  # a Category heads the properties that follow it
            if _tag(el) == "Category":
                category = _text(el)
            elif _tag(el) == "Property":
                key = _attr(el, "key")
                if not key:
                    continue
                choices, min_len, max_len = _qualifiers(_attr(el, "qualifiers"))
                desc.properties.append(
                    OvfProperty(
                        key=key,
                        qualified_key=".".join(p for p in (cls, key, instance) if p),
                        type=_attr(el, "type") or "string",
                        label=_text(_child(el, "Label")),
                        description=_text(_child(el, "Description")),
                        category=category,
                        default=_attr(el, "value"),
                        password=(_attr(el, "password") or "").lower() == "true",
                        user_configurable=(_attr(el, "userConfigurable") or "").lower() == "true",
                        choices=choices,
                        min_length=min_len,
                        max_length=max_len,
                    )
                )

    for el in root.iter():
        tag = _tag(el)
        if tag == "Network" and _attr(el, "name"):
            desc.networks.append(
                OvfNetwork(name=_attr(el, "name") or "", description=_text(_child(el, "Description")))
            )
        elif tag == "VirtualHardwareSection" and (transport := _attr(el, "transport")):
            desc.transport = [t for t in transport.replace(",", " ").split() if t]
        elif tag == "Configuration" and _attr(el, "id"):
            desc.deployment_options.append(
                DeploymentOption(
                    id=_attr(el, "id") or "",
                    label=_text(_child(el, "Label")),
                    default=(_attr(el, "default") or "").lower() == "true",
                )
            )
        elif tag == "Item":
            kind = _text(el.find(f"{{{RASD}}}ResourceType"))
            quantity = _text(el.find(f"{{{RASD}}}VirtualQuantity"))
            if kind == "3" and quantity and desc.cpus is None:
                desc.cpus = int(quantity)
            elif kind == "4" and quantity and desc.memory_mb is None:
                units = _text(el.find(f"{{{RASD}}}AllocationUnits")) or "byte * 2^20"
                desc.memory_mb = _megabytes(int(quantity), units)
        elif tag == "Disk" and (capacity := _attr(el, "capacity")) and capacity.isdigit():
            units = _attr(el, "capacityAllocationUnits") or "byte"
            desc.disk_gb = (desc.disk_gb or 0) + _megabytes(int(capacity), units) / 1024
    return desc


def _megabytes(quantity: int, units: str) -> int:
    m = re.search(r"2\^(\d+)", units)
    power = int(m.group(1)) if m else 0
    return int(quantity * 2**power / 2**20)


def read_ova(path: Path) -> tuple[str, dict[str, int]]:
    """The OVF descriptor text and the size of every file in the OVA (a tar; the descriptor comes first)."""
    try:
        with tarfile.open(path) as tar:
            members = tar.getmembers()
            ovf = next((m for m in members if m.name.endswith(".ovf")), None)
            if ovf is None:
                raise DescriptorError(f"{path.name} has no OVF descriptor")
            if ovf.size > MAX_DESCRIPTOR_BYTES:
                raise DescriptorError(f"{path.name}: the OVF descriptor is unexpectedly large")
            handle = tar.extractfile(ovf)
            xml = handle.read().decode(errors="replace") if handle else ""
    except (OSError, tarfile.TarError) as exc:
        raise DescriptorError(f"{path.name} is not a readable OVA: {exc}") from exc
    return xml, {m.name: m.size for m in members}


def read_ova_descriptor(path: Path) -> OvfDescriptor:
    return parse_descriptor(read_ova(path)[0])


def _property_schema(p: OvfProperty) -> dict[str, Any]:
    node: dict[str, Any] = {"title": p.label or p.key}
    if p.description:
        node["description"] = p.description
    if p.category:
        node["x-group"] = p.category
    if p.type == "boolean":
        node["type"] = "boolean"
        if p.default is not None:
            node["default"] = p.default.lower() == "true"
        return node
    if p.type in _INTEGER_TYPES:
        node["type"] = "integer"
    elif p.type == "real":
        node["type"] = "number"
    else:
        node["type"] = "string"
    if p.choices:
        node["enum"] = p.choices
    if p.min_length is not None:
        node["minLength"] = p.min_length
    if p.max_length is not None:
        node["maxLength"] = p.max_length
    if p.password:
        node["format"] = "password"
        node["writeOnly"] = True
    if p.default not in (None, "") and not p.password:
        node["default"] = (
            int(p.default) if node["type"] == "integer" and p.default.lstrip("-").isdigit() else p.default
        )
    return node


def descriptor_schema(desc: OvfDescriptor) -> dict[str, Any]:
    """JSON Schema of the inputs a person sets (the user-configurable properties), keyed by qualified key.

    Properties the OVA does not mark user-configurable are not asked for; they still reach the guest with
    their defaults (see ``environment_values``).
    """
    props = [p for p in desc.properties if p.user_configurable]
    return {
        "title": desc.product or "Appliance",
        "type": "object",
        "properties": {p.qualified_key: _property_schema(p) for p in props},
        "x-secret-fields": [p.qualified_key for p in props if p.password],
    }


def environment_values(desc: OvfDescriptor, values: dict[str, Any]) -> dict[str, str]:
    """Every property the OVA declares, as the guest reads it: the given value, else the default, else "".

    vCenter sends all properties; appliances' first-boot scripts can fail on a key that is absent.
    """
    given = desc.qualify(values)
    out: dict[str, str] = {}
    for p in desc.properties:
        value = given.get(p.qualified_key, p.default if p.default is not None else "")
        out[p.qualified_key] = ("True" if value else "False") if isinstance(value, bool) else str(value)
    return out
