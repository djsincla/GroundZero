"""Hand-built iDRAC9 / PowerEdge R740xd Redfish responses.

Synthetic stand-in until real sanitized captures exist
(`groundzero dev capture --bmc ... --out tests/fixtures/dell-r740xd`).
Returns a fresh dict each call so tests can mutate it.
"""

from __future__ import annotations

from typing import Any

SYS = "/redfish/v1/Systems/System.Embedded.1"
MGR = "/redfish/v1/Managers/iDRAC.Embedded.1"


def _collection(*paths: str) -> dict[str, Any]:
    return {"Members": [{"@odata.id": p} for p in paths], "Members@odata.count": len(paths)}


def _drive(ident: str, media: str, protocol: str, capacity: int, model: str) -> dict[str, Any]:
    return {
        "@odata.id": f"{SYS}/Storage/Drives/{ident}",
        "Id": ident,
        "Name": ident,
        "Model": model,
        "MediaType": media,
        "Protocol": protocol,
        "CapacityBytes": capacity,
        "SerialNumber": "S0000000",
        "Status": {"State": "Enabled", "Health": "OK"},
    }


def responses() -> dict[str, dict[str, Any]]:
    cpu = {
        "ProcessorType": "CPU",
        "Manufacturer": "Intel",
        "Model": "Intel(R) Xeon(R) Gold 6230 CPU @ 2.10GHz",
        "TotalCores": 20,
        "TotalThreads": 40,
        "MaxSpeedMHz": 4000,
        "Status": {"State": "Enabled"},
    }
    ssd = [_drive(f"Disk.Bay.{i}", "SSD", "SAS", 1_920_383_410_176, "MZILT1T9HBJR0D3") for i in (0, 1)]
    hdd = [_drive(f"Disk.Bay.{i}", "HDD", "SAS", 2_399_832_817_664, "ST2400MM0129") for i in (2, 3)]
    boss = _drive("Disk.Direct.0-0:AHCI.Slot.6-1", "SSD", "SATA", 240_057_409_536, "MTFDDAV240TCB")
    r: dict[str, dict[str, Any]] = {
        "/redfish/v1": {
            "RedfishVersion": "1.11.0",
            "Vendor": "Dell",
            "Product": "Integrated Dell Remote Access Controller",
            "Oem": {"Dell": {}},
            "Systems": {"@odata.id": "/redfish/v1/Systems"},
            "Managers": {"@odata.id": "/redfish/v1/Managers"},
            "Chassis": {"@odata.id": "/redfish/v1/Chassis"},
        },
        "/redfish/v1/Systems": _collection(SYS),
        "/redfish/v1/Managers": _collection(MGR),
        "/redfish/v1/Chassis": _collection("/redfish/v1/Chassis/System.Embedded.1"),
        SYS: {
            "@odata.id": SYS,
            "Manufacturer": "Dell Inc.",
            "Model": "PowerEdge R740xd",
            "SerialNumber": "ABC1234",
            "BiosVersion": "2.19.1",
            "PowerState": "On",
            "Status": {"Health": "OK", "HealthRollup": "OK"},
            "MemorySummary": {"TotalSystemMemoryGiB": 384},
            "Processors": {"@odata.id": f"{SYS}/Processors"},
            "Memory": {"@odata.id": f"{SYS}/Memory"},
            "Storage": {"@odata.id": f"{SYS}/Storage"},
            "EthernetInterfaces": {"@odata.id": f"{SYS}/EthernetInterfaces"},
            "Bios": {"@odata.id": f"{SYS}/Bios"},
            "VirtualMedia": {"@odata.id": f"{SYS}/VirtualMedia"},
            "Boot": {
                "BootSourceOverrideEnabled": "Disabled",
                "BootSourceOverrideTarget": "None",
                "BootSourceOverrideMode": "UEFI",
                "BootSourceOverrideTarget@Redfish.AllowableValues": [
                    "None",
                    "Pxe",
                    "Floppy",
                    "Cd",
                    "Hdd",
                    "BiosSetup",
                    "Utilities",
                    "UefiTarget",
                    "SDCard",
                    "UefiHttp",
                ],
            },
            "Actions": {
                "#ComputerSystem.Reset": {
                    "target": f"{SYS}/Actions/ComputerSystem.Reset",
                    "ResetType@Redfish.AllowableValues": [
                        "On",
                        "ForceOff",
                        "ForceRestart",
                        "GracefulRestart",
                        "GracefulShutdown",
                        "PushPowerButton",
                        "Nmi",
                        "PowerCycle",
                    ],
                }
            },
        },
        f"{SYS}/Processors": _collection(f"{SYS}/Processors/CPU.Socket.1", f"{SYS}/Processors/CPU.Socket.2"),
        f"{SYS}/Processors/CPU.Socket.1": {**cpu, "Socket": "CPU.Socket.1"},
        f"{SYS}/Processors/CPU.Socket.2": {**cpu, "Socket": "CPU.Socket.2"},
        f"{SYS}/Memory": _collection(*(f"{SYS}/Memory/DIMM.Socket.A{i}" for i in range(1, 13))),
        f"{SYS}/Storage": _collection(f"{SYS}/Storage/RAID.Integrated.1-1", f"{SYS}/Storage/AHCI.Slot.6-1"),
        f"{SYS}/Storage/RAID.Integrated.1-1": {
            "Id": "RAID.Integrated.1-1",
            "StorageControllers": [{"Name": "PERC H740P Mini", "Model": "PERC H740P Mini"}],
            "Drives": [{"@odata.id": d["@odata.id"]} for d in ssd + hdd],
        },
        f"{SYS}/Storage/AHCI.Slot.6-1": {
            "Id": "AHCI.Slot.6-1",
            "StorageControllers": [{"Name": "BOSS-S1", "Model": "BOSS-S1"}],
            "Drives": [{"@odata.id": boss["@odata.id"]}],
        },
        f"{SYS}/EthernetInterfaces": _collection(
            f"{SYS}/EthernetInterfaces/NIC.Integrated.1-1-1", f"{SYS}/EthernetInterfaces/NIC.Integrated.1-2-1"
        ),
        f"{SYS}/EthernetInterfaces/NIC.Integrated.1-1-1": {
            "Id": "NIC.Integrated.1-1-1",
            "MACAddress": "00:00:5E:00:53:01",
            "LinkStatus": "LinkUp",
            "SpeedMbps": 25000,
        },
        f"{SYS}/EthernetInterfaces/NIC.Integrated.1-2-1": {
            "Id": "NIC.Integrated.1-2-1",
            "MACAddress": "00:00:5E:00:53:02",
            "LinkStatus": "LinkDown",
            "SpeedMbps": 0,
        },
        f"{SYS}/Bios": {
            "Attributes": {
                "ProcVirtualization": "Enabled",
                "BootMode": "Uefi",
                "SriovGlobalEnable": "Enabled",
            }
        },
        f"{SYS}/VirtualMedia": _collection(f"{SYS}/VirtualMedia/1"),
        f"{SYS}/VirtualMedia/1": {
            "@odata.id": f"{SYS}/VirtualMedia/1",
            "Name": "Virtual CD",
            "MediaTypes": ["CD", "DVD"],
            "Inserted": False,
            "Image": None,
            "Actions": {
                "#VirtualMedia.InsertMedia": {
                    "target": f"{SYS}/VirtualMedia/1/Actions/VirtualMedia.InsertMedia",
                    "TransferProtocolType@Redfish.AllowableValues": ["CIFS", "HTTP", "HTTPS", "NFS"],
                },
                "#VirtualMedia.EjectMedia": {
                    "target": f"{SYS}/VirtualMedia/1/Actions/VirtualMedia.EjectMedia"
                },
            },
        },
        MGR: {
            "@odata.id": MGR,
            "FirmwareVersion": "7.00.00.171",
            "VirtualMedia": {"@odata.id": f"{MGR}/VirtualMedia"},
        },
        f"{MGR}/VirtualMedia": _collection(),
        "/redfish/v1/LicenseService/Licenses": _collection("/redfish/v1/LicenseService/Licenses/FD000001"),
        "/redfish/v1/LicenseService/Licenses/FD000001": {
            "Id": "FD000001",
            "Description": "iDRAC9 x5 Enterprise License",
        },
    }
    for d in [*ssd, *hdd, boss]:
        r[d["@odata.id"]] = d
    return r
