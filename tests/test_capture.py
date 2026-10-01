from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import make_client

from groundzero.inventory.collect import collect_inventory
from groundzero.redfish.capture import Pseudonymizer, Recorder, load_recording, pseudonymize, sanitize


def test_sanitize_redacts_identifiers() -> None:
    raw = {
        "SerialNumber": "ABC1234",
        "UUID": "4c4c4544-0000",
        "MACAddress": "AA:BB:CC:DD:EE:FF",
        "HostName": "r740xd.lab.local",
        "Description": "Reachable at 10.1.2.3 via aa:bb:cc:dd:ee:01",
        "Model": "PowerEdge R740xd",
        "@odata.id": "/redfish/v1/Systems/System.Embedded.1",
    }
    clean = sanitize(raw)
    assert clean["SerialNumber"] == clean["UUID"] == clean["MACAddress"] == clean["HostName"] == "REDACTED"
    assert clean["Description"] == "Reachable at 192.0.2.10 via 00:00:5E:00:53:00"
    assert clean["Model"] == "PowerEdge R740xd"
    assert clean["@odata.id"] == raw["@odata.id"]


async def test_record_and_replay_round_trip(tmp_path: Path, idrac9: dict[str, Any]) -> None:
    recorder = Recorder()
    async with make_client(idrac9, on_response=recorder) as client:
        _, original = await collect_inventory(client)
    assert recorder.write(tmp_path) == len(recorder.responses)

    async with make_client(load_recording(tmp_path)) as client:
        _, replayed = await collect_inventory(client)
    assert replayed.total_cores == original.total_cores
    assert replayed.system.serial_number == "REDACTED"


def test_pseudonyms_are_consistent_and_keep_netmasks() -> None:
    pseudo = Pseudonymizer()
    data = {
        "vmk": {"ip": "192.0.2.101", "netmask": "255.255.255.0", "mac": "18:66:DA:85:7F:C2"},
        "nic": {"mac": "18:66:da:85:7f:c2"},
        "gateway": "192.0.2.1",
        "again": "192.0.2.101",
    }
    clean = pseudonymize(data, pseudo)
    assert clean["vmk"]["netmask"] == "255.255.255.0"
    assert clean["vmk"]["ip"] == clean["again"] != clean["gateway"]
    assert clean["vmk"]["mac"] == clean["nic"]["mac"]  # relationships survive
    assert "10.7." not in str(clean) and "18:66" not in str(clean).lower()
