"""Record sanitized Redfish responses for offline replay (test fixtures), and replay them.

Recording piggybacks on the real inventory collector, so fixtures contain exactly the resources it reads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

_SENSITIVE_KEY = re.compile(
    r"serial|servicetag|uuid|mac|ipv4|ipv6|hostname|fqdn|assettag|expressservicecode|nodeid|dns|"
    r"address|gateway|domainname|partnumber|sku|entitlement",
    re.IGNORECASE,
)
_KEEP_KEYS = frozenset({"@odata.id", "@odata.type", "@odata.context", "target", "MACAddress@odata.count"})
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_MAC = re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b")


class Pseudonymizer:
    """Replace IPv4/MAC addresses with documentation-range stand-ins, consistently (same in → same out)."""

    def __init__(self) -> None:
        self._ips: dict[str, str] = {}
        self._macs: dict[str, str] = {}

    def ip(self, match: re.Match[str]) -> str:
        value = match.group(0)
        if value.startswith("255.") or value == "0.0.0.0":  # netmasks / unset: not identifying, keep layout
            return value
        return self._ips.setdefault(value, f"192.0.2.{10 + len(self._ips)}")

    def mac(self, match: re.Match[str]) -> str:
        n = len(self._macs)
        return self._macs.setdefault(
            match.group(0).lower(), f"00:00:5E:00:{0x53 + n // 256:02X}:{n % 256:02X}"
        )

    def text(self, value: str) -> str:
        return _MAC.sub(self.mac, _IPV4.sub(self.ip, value))


def pseudonymize(value: Any, pseudo: Pseudonymizer) -> Any:
    """Rewrite every IP/MAC inside a JSON-like value, keeping structure and relationships intact."""
    if isinstance(value, dict):
        return {k: pseudonymize(v, pseudo) for k, v in value.items()}
    if isinstance(value, list):
        return [pseudonymize(v, pseudo) for v in value]
    return pseudo.text(value) if isinstance(value, str) else value


_VERSION_KEY = re.compile(r"version|build|release|firmware|revision", re.IGNORECASE)


def sanitize(
    value: Any, key: str = "", pseudo: Pseudonymizer | None = None, settings: frozenset[str] = frozenset()
) -> Any:
    """``settings``: values a BIOS attribute registry lists as allowed (Enabled, OnConRedirAuto, ...). They
    are choices, not identifiers, so they're kept even under a key that sounds sensitive (SerialComm)."""
    pseudo = pseudo or Pseudonymizer()
    if isinstance(value, dict):
        return {k: sanitize(v, k, pseudo, settings) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, key, pseudo, settings) for v in value]
    if isinstance(value, str):
        if value in settings:
            return value
        if key not in _KEEP_KEYS and _SENSITIVE_KEY.search(key) and value:
            return "REDACTED"
        if _VERSION_KEY.search(key):  # versions like 7.10.70.00 or 9.0.1.0 look like IPv4 addresses
            return value
        return pseudo.text(value)
    return value


def registry_values(responses: dict[str, dict[str, Any]]) -> frozenset[str]:
    """Every allowed value named by any attribute registry among the recorded responses."""
    found: set[str] = set()
    for body in responses.values():
        for attr in (body.get("RegistryEntries") or {}).get("Attributes") or []:
            found.update(str(v["ValueName"]) for v in attr.get("Value") or [] if "ValueName" in v)
    return frozenset(found)


def _filename(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/")) + ".json"


class Recorder:
    def __init__(self) -> None:
        self.responses: dict[str, dict[str, Any]] = {}

    def __call__(self, path: str, body: dict[str, Any]) -> None:
        self.responses[path] = body

    def write(self, directory: Path) -> int:
        directory.mkdir(parents=True, exist_ok=True)
        index: dict[str, str] = {}
        pseudo = Pseudonymizer()
        settings = registry_values(self.responses)
        for path, body in sorted(self.responses.items()):
            name = _filename(path)
            index[path] = name
            clean = sanitize(body, pseudo=pseudo, settings=settings)
            (directory / name).write_text(json.dumps(clean, indent=2, sort_keys=True) + "\n")
        (directory / "index.json").write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
        return len(index)


def load_recording(directory: Path) -> dict[str, dict[str, Any]]:
    """Load a fixture directory written by ``Recorder.write`` into a path → body mapping."""
    index: dict[str, str] = json.loads((directory / "index.json").read_text())
    return {path: json.loads((directory / name).read_text()) for path, name in index.items()}


def replay_transport(
    responses: dict[str, dict[str, Any]], *, token: str = "fixture-token"
) -> httpx.MockTransport:
    """An httpx transport that serves recorded GETs and accepts session login/logout."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        if request.method == "POST" and path.endswith("/Sessions"):
            return httpx.Response(
                201,
                headers={"X-Auth-Token": token, "Location": "/redfish/v1/SessionService/Sessions/1"},
                json={"Id": "1"},
            )
        if request.method == "DELETE" and "/Sessions/" in path:
            return httpx.Response(204)
        if request.method == "GET" and path in responses:
            return httpx.Response(200, json=responses[path])
        return httpx.Response(404, json={"error": {"code": "Base.1.0.ResourceMissingAtURI", "message": path}})

    return httpx.MockTransport(handler)
