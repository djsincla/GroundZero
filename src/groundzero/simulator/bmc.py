"""A stateful simulated BMC (iDRAC-shaped) built on a recorded Redfish capture.

Implements what an install drives: InsertMedia/EjectMedia, one-time boot (Dell attributes or the
standard Boot override), ComputerSystem.Reset and the session service. Like a real BMC it *fetches*
the virtual media URL over HTTPS, so a simulation run exercises GroundZero's real media server.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from groundzero.redfish.bios_registry import BiosRegistry, parse_registry
from groundzero.simulator.esxi import SimulatedEsxi

logger = logging.getLogger(__name__)

_TOKEN = "simulated-session"


class SimulatedBmc:
    def __init__(
        self,
        responses: dict[str, dict[str, Any]],
        esxi: SimulatedEsxi | None = None,
        faults: frozenset[str] = frozenset(),
        hostname: str = "idrac-esxi1",
    ) -> None:
        """``faults`` injects misbehaviour seen on real BMCs, for tests:

        - "ignore-boot-once": the one-time boot override is accepted but not honoured
        - "slow-insert": InsertMedia takes effect but its response times out
        - "late-attach": InsertMedia fails (RAC0720) but the image attaches a moment later
        - "kickstart-error": the installer boots, rejects KS.CFG and reboots into the old ESXi
        - "bios-wrong": the BIOS starts with processor virtualization off and legacy (BIOS) boot mode
        - "bios-not-applied": pending BIOS settings are accepted but never applied (a failed config job)
        - "perc-drives": the (empty) PERC gets four 960 GB SAS SSDs, and its mode can be changed
        - "storage-not-applied": storage changes waiting for a reset are accepted but never applied
        """
        self.responses = copy.deepcopy(responses)
        self.esxi = esxi
        self.faults = faults
        self.attributes: dict[str, str] = {
            "ServerBoot.1.BootOnce": "Disabled",
            "ServerBoot.1.FirstBootDevice": "Normal",
            "RFS.1.MediaAttachState": "Detached",
            "RFS.1.Status": "Done",
        }
        self.attach_delay = 0.5  # the real iDRAC took ~55 s
        self.media: dict[str, str | None] = {}  # slot path -> image URL
        self.writes: list[str] = []
        self._tasks: set[asyncio.Task[None]] = set()
        system = self._system_path()
        self.responses.setdefault(system, {}).setdefault("PowerState", "On")
        self._add_bmc_nic(hostname)
        self.pending_bios: dict[str, Any] = {}  # Bios/Settings: applied on the next reset, like the iDRAC
        self.pending_storage: list[Callable[[], None]] = []  # storage jobs that run at the next POST
        if "perc-drives" in faults:
            self._add_perc_drives()
        if "bios-wrong" in faults and (bios := self._bios_path()):
            self.responses[bios].setdefault("Attributes", {}).update(
                {"ProcVirtualization": "Disabled", "BootMode": "Bios"}
            )

    def _add_bmc_nic(self, hostname: str) -> None:
        """The BMC's own network interface (recordings redact it): where its DNS name is reported."""
        manager = next(
            (p for p in self.responses if p.rstrip("/").count("/") == 4 and "/Managers/" in p), None
        )
        if manager is None:
            return
        nics = f"{manager}/EthernetInterfaces"
        nic = f"{nics}/NIC.1"
        self.responses[manager].setdefault("EthernetInterfaces", {"@odata.id": nics})
        self.responses.setdefault(nics, {"Members": [{"@odata.id": nic}], "Members@odata.count": 1})
        self.responses[nic] = {
            "@odata.id": nic,
            "Id": "NIC.1",
            "HostName": hostname,
            "FQDN": f"{hostname}.lab.example",
        }

    def _bios_path(self) -> str | None:
        return next((p for p in self.responses if p.endswith("/Bios") and "/Systems/" in p), None)

    def _system_path(self) -> str:
        return next(p for p in self.responses if p.rstrip("/").count("/") == 4 and "/Systems/" in p)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    # ── request handling ─────────────────────────────────────────────────
    async def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        body = json.loads(request.content) if request.content else {}
        if request.method != "GET":
            self.writes.append(f"{request.method} {path}")
        if request.method == "POST" and path.endswith("/Sessions"):
            location = "/redfish/v1/SessionService/Sessions/1"
            return httpx.Response(201, headers={"X-Auth-Token": _TOKEN, "Location": location}, json={})
        if request.method == "DELETE" and "/Sessions/" in path:
            return httpx.Response(204)
        if request.method == "GET":
            return self._get(path)
        if request.method == "PATCH":
            return self._patch(path, body)
        if request.method == "POST" and path.endswith("VirtualMedia.InsertMedia"):
            return await self._insert(path.rsplit("/Actions/", 1)[0], body)
        if request.method == "POST" and path.endswith("VirtualMedia.EjectMedia"):
            slot = path.rsplit("/Actions/", 1)[0]
            if not self.media.get(slot):
                return _error(500, "No Virtual Media devices are currently connected.")
            self.media[slot] = None
            self.attributes.update({"RFS.1.MediaAttachState": "Detached", "RFS.1.Status": "Done"})
            return httpx.Response(204)
        if request.method == "POST" and path.endswith("ComputerSystem.Reset"):
            return self._reset(body.get("ResetType", ""))
        if request.method == "DELETE" and "/Volumes/" in path:
            return self._delete_volume(path)
        if request.method == "POST" and path.endswith("/Volumes"):
            return self._create_volume(path, body)
        if request.method == "POST" and "/DellRaidService/Actions/" in path:
            return self._raid_service(path.rsplit(".", 1)[-1], body)
        return _error(405, f"{request.method} {path} not supported by the simulator")

    def _get(self, path: str) -> httpx.Response:
        if path.endswith("/Bios/Settings"):
            return httpx.Response(200, json={"Attributes": dict(self.pending_bios)})
        if path.endswith("/Attributes") and "/Managers/" in path:
            return httpx.Response(200, json={"Attributes": dict(self.attributes)})
        data = self.responses.get(path)
        if data is None:
            return _error(404, f"{path} not found")
        data = copy.deepcopy(data)
        if path in self.media or "VirtualMedia/" in path:
            image = self.media.get(path)
            data.update(
                {"Inserted": bool(image), "Image": image, "ConnectedVia": "URI" if image else "NotConnected"}
            )
        return httpx.Response(200, json=data)

    def _bios_registry(self, bios_path: str) -> BiosRegistry | None:
        body = self.responses.get(f"{bios_path}/BiosRegistry")
        return parse_registry(body) if body else None

    # ── storage: volumes, controller mode, drive state, spares (Dell PERC behaviour) ──
    def _add_perc_drives(self) -> None:
        storage = next((p for p in self.responses if p.endswith("/Storage/RAID.Slot.6-1")), None)
        if storage is None:
            return
        drives = []
        for i in range(4):
            drive_id = f"Disk.Bay.{i}:Enclosure.Internal.0-1:RAID.Slot.6-1"
            path = f"{storage}/Drives/{drive_id}"
            self.responses[path] = {
                "@odata.id": path,
                "Id": drive_id,
                "Name": f"Solid State Disk 0:1:{i}",
                "Model": "KPM5XVUG960G",
                "MediaType": "SSD",
                "Protocol": "SAS",
                "CapacityBytes": 960197124096,
                "HotspareType": "None",
                "Status": {"Health": "OK", "State": "Enabled"},
                "Links": {"Volumes": []},
                "Oem": {"Dell": {"DellPhysicalDisk": {"RaidStatus": "Ready"}}},
            }
            drives.append({"@odata.id": path})
        self.responses[storage]["Drives"] = drives
        self.responses[storage]["Drives@odata.count"] = len(drives)
        self.responses[storage]["@Redfish.Settings"] = {
            "SettingsObject": {"@odata.id": f"{storage}/Settings"}
        }

    def _queue(self, change: Callable[[], None], apply_time: str | None) -> httpx.Response:
        """Immediate changes happen now; OnReset ones wait for the next POST, as a staged iDRAC job does."""
        if apply_time == "Immediate":
            change()
        else:
            self.pending_storage.append(change)
        return httpx.Response(
            202, json={}, headers={"Location": "/redfish/v1/TaskService/Tasks/JID_SIMULATED"}
        )

    def _drive_path(self, drive_id: str) -> str | None:
        return next((p for p in self.responses if p.endswith(f"/Drives/{drive_id}")), None)

    def _set_drive_state(self, drive_id: str, state: str) -> None:
        if (path := self._drive_path(drive_id)) is not None:
            self.responses[path].setdefault("Oem", {}).setdefault("Dell", {}).setdefault(
                "DellPhysicalDisk", {}
            )["RaidStatus"] = state

    def _apply_time(self, collection: str, requested: str | None) -> str:
        supported = (self.responses.get(collection, {}).get("@Redfish.OperationApplyTimeSupport") or {}).get(
            "SupportedValues", []
        )
        if requested:
            return requested
        return "Immediate" if "Immediate" in supported else "OnReset"

    def _create_volume(self, collection: str, body: dict[str, Any]) -> httpx.Response:
        if collection not in self.responses:
            return _error(404, f"{collection} not found")
        drive_paths = [d["@odata.id"] for d in (body.get("Links") or {}).get("Drives", [])]
        missing = [d for d in drive_paths if d not in self.responses]
        if missing or not drive_paths:
            return _error(400, f"Unknown drive(s): {', '.join(missing) or 'none given'}")
        raid = body.get("RAIDType")
        busy = [d for d in drive_paths if self.responses[d].get("Links", {}).get("Volumes")]
        if busy:
            return _error(400, f"Drive(s) already in a volume: {', '.join(busy)}")

        def create() -> None:
            controller = collection.rsplit("/Volumes", 1)[0].rsplit("/", 1)[-1]
            index = sum(1 for p in self.responses if p.startswith(collection + "/"))
            volume_id = f"Disk.Virtual.{index}:{controller}"
            path = f"{collection}/{volume_id}"
            sizes = [self.responses[d].get("CapacityBytes", 0) for d in drive_paths]
            usable = {
                "RAID0": len(sizes),
                "RAID1": 1,
                "RAID5": len(sizes) - 1,
                "RAID6": len(sizes) - 2,
                "RAID10": len(sizes) // 2,
            }.get(str(raid), 1)
            self.responses[path] = {
                "@odata.id": path,
                "Id": volume_id,
                "Name": body.get("Name") or volume_id,
                "RAIDType": raid,
                "VolumeType": "Mirrored" if raid == "RAID1" else "StripedWithParity",
                "CapacityBytes": min(sizes) * usable,
                "Links": {"Drives": [{"@odata.id": d} for d in drive_paths]},
            }
            self.responses[collection].setdefault("Members", []).append({"@odata.id": path})
            for d in drive_paths:
                self.responses[d].setdefault("Links", {})["Volumes"] = [{"@odata.id": path}]
                self._set_drive_state(self.responses[d]["Id"], "Online")

        return self._queue(create, self._apply_time(collection, body.get("@Redfish.OperationApplyTime")))

    def _delete_volume(self, path: str) -> httpx.Response:
        volume = self.responses.get(path)
        if volume is None:
            return _error(404, f"{path} not found")
        collection = path.rsplit("/", 1)[0]

        def delete() -> None:
            for d in volume.get("Links", {}).get("Drives", []):
                drive = self.responses.get(d["@odata.id"])
                if drive is not None:
                    drive.setdefault("Links", {})["Volumes"] = []
                    self._set_drive_state(drive["Id"], "Ready")
            members = self.responses[collection].get("Members", [])
            self.responses[collection]["Members"] = [m for m in members if m.get("@odata.id") != path]
            self.responses.pop(path, None)

        return self._queue(delete, self._apply_time(collection, None))

    def _raid_service(self, action: str, body: dict[str, Any]) -> httpx.Response:
        if action in ("ConvertToRAID", "ConvertToNonRAID"):
            ids = list(body.get("PDArray") or [])
            unknown = [d for d in ids if self._drive_path(d) is None]
            if unknown or not ids:
                return _error(400, f"Unknown drive(s): {', '.join(unknown) or 'none given'}")
            state = "Ready" if action == "ConvertToRAID" else "NonRAID"

            def convert() -> None:
                for drive_id in ids:
                    self._set_drive_state(drive_id, state)

            return self._queue(convert, "OnReset")
        if action == "AssignSpare":
            drive = self._drive_path(str(body.get("TargetFQDD", "")))
            if drive is None:
                return _error(400, f"Unknown drive {body.get('TargetFQDD')}")
            return self._queue(lambda: self.responses[drive].update({"HotspareType": "Global"}), "OnReset")
        return _error(405, f"DellRaidService.{action} not supported by the simulator")

    def _patch(self, path: str, body: dict[str, Any]) -> httpx.Response:
        if path.endswith("/Bios/Settings"):
            current = self.responses.get(path.removesuffix("/Settings"), {}).get("Attributes", {})
            unknown = sorted(k for k in body.get("Attributes", {}) if k not in current)
            if unknown:
                return _error(400, f"Unknown BIOS attribute(s): {', '.join(unknown)}")
            registry = self._bios_registry(path.removesuffix("/Settings"))
            if registry is not None:  # as the iDRAC does: read-only and out-of-range values are refused
                problems = registry.check(body.get("Attributes", {}))
                if problems:
                    return _error(400, "; ".join(f"{name}: {message}" for name, message, _ in problems))
            self.pending_bios.update(body.get("Attributes", {}))
            return httpx.Response(202, json={})
        if path.endswith("/Settings") and "/Storage/" in path:
            storage = path.removesuffix("/Settings")
            mode = (((body.get("Oem") or {}).get("Dell") or {}).get("DellStorageController") or {}).get(
                "ControllerMode"
            )
            if (
                storage not in self.responses
                or "@Redfish.Settings" not in self.responses[storage]
                or not mode
            ):
                return _error(400, "This controller's mode can't be changed")

            def set_mode() -> None:
                dell = self.responses[storage].setdefault("Oem", {}).setdefault("Dell", {})
                dell.setdefault("DellController", {})["CurrentControllerMode"] = mode

            return self._queue(set_mode, "OnReset")
        if path.endswith("/Attributes"):
            self.attributes.update({k: str(v) for k, v in body.get("Attributes", {}).items()})
            return httpx.Response(200, json={})
        if path in self.responses and "Boot" in body:
            self.responses[path].setdefault("Boot", {}).update(body["Boot"])
            return httpx.Response(200, json={})
        return _error(405, f"PATCH {path} not supported")

    async def _insert(self, slot: str, body: dict[str, Any]) -> httpx.Response:
        if self.media.get(slot):
            return _error(500, "Virtual Media is detached or Virtual Media devices are already in use.")
        url = str(body.get("Image", ""))
        try:  # a real BMC validates the share by reading from it
            async with httpx.AsyncClient(verify=False, timeout=30) as http:
                head = await http.head(url)
                head.raise_for_status()
                (await http.get(url, headers={"Range": "bytes=0-65535"})).raise_for_status()
        except httpx.HTTPError:
            return _error(
                500, "Unable to locate the ISO or IMG image file or folder in the network share location"
            )
        if "late-attach" in self.faults:
            # Seen live: RAC0720 returned, then the same image attached about a minute later.
            self._spawn(self._attach_later(slot, url))
            return _error(
                500, "Unable to locate the ISO or IMG image file or folder in the network share location"
            )
        self.media[slot] = url
        self.attributes.update({"RFS.1.MediaAttachState": "Detached", "RFS.1.Status": "Pending"})
        self._spawn(self._finish_attach())
        if "slow-insert" in self.faults:
            # Seen live: the mount completes but the response never arrives in time.
            raise httpx.ReadTimeout("simulated slow InsertMedia", request=None)
        return httpx.Response(204)

    async def _attach_later(self, slot: str, url: str) -> None:
        await asyncio.sleep(1.0)
        self.media[slot] = url
        self.attributes.update({"RFS.1.MediaAttachState": "Attached", "RFS.1.Status": "Done"})

    async def _finish_attach(self) -> None:
        await asyncio.sleep(self.attach_delay)
        if any(self.media.values()):
            self.attributes.update({"RFS.1.MediaAttachState": "Attached", "RFS.1.Status": "Done"})

    def _reset(self, reset_type: str) -> httpx.Response:
        system = self.responses[self._system_path()]
        if reset_type not in ("On", "ForceRestart", "GracefulRestart", "PowerCycle"):
            return _error(400, f"Unsupported ResetType {reset_type}")
        system["PowerState"] = "On"
        if self.pending_storage:  # the controller's configuration jobs run during POST
            if "storage-not-applied" not in self.faults:
                for change in self.pending_storage:
                    change()
            self.pending_storage = []
        if self.pending_bios and (bios := self._bios_path()):  # the BIOS config job runs during POST
            if "bios-not-applied" not in self.faults:
                self.responses[bios].setdefault("Attributes", {}).update(self.pending_bios)
            self.pending_bios = {}
        # Like the real iDRAC: an RFS that has not finished attaching is an empty drive at POST.
        attached = self.attributes.get("RFS.1.MediaAttachState") == "Attached"
        boot_cd = self._consume_one_time_cd_boot() and attached and "ignore-boot-once" not in self.faults
        image = next((url for url in self.media.values() if url), None)
        if self.esxi is not None:
            previous = self.esxi.about
            self.esxi.power_off()
            if boot_cd and image:
                self._spawn(self._boot_installer(image))
            elif previous is not None:
                self._spawn(self.esxi.boot_existing(previous))
        return httpx.Response(204)

    def _consume_one_time_cd_boot(self) -> bool:
        """Apply and clear a pending one-time boot; True if it targets the virtual CD (RFS) device.

        Mirrors what the real R740xd (iDRAC 7.x) did: the Dell ServerBoot FirstBootDevice=VCD-DVD
        attribute is consumed but does NOT boot Redfish-mounted (RFS) media; UefiTarget at the
        "Virtual Optical Drive" boot option does.
        """
        boot = self.responses[self._system_path()].setdefault("Boot", {})
        if self.attributes.get("ServerBoot.1.FirstBootDevice") != "Normal":
            self.attributes["ServerBoot.1.FirstBootDevice"] = "Normal"  # consumed, boots nothing from RFS
        if boot.get("BootSourceOverrideEnabled") != "Once":
            return False
        target = boot.get("BootSourceOverrideTarget")
        path = boot.get("UefiTargetBootSourceOverride")
        boot.update({"BootSourceOverrideEnabled": "Disabled", "BootSourceOverrideTarget": "None"})
        if target == "Cd":
            return True
        if target == "UefiTarget":
            options = [v for k, v in self.responses.items() if "/BootOptions/" in k]
            return any(
                o.get("UefiDevicePath") == path and "virtual optical" in str(o.get("DisplayName", "")).lower()
                for o in options
            )
        return False

    async def _boot_installer(self, url: str) -> None:
        assert self.esxi is not None
        try:
            async with httpx.AsyncClient(verify=False, timeout=60) as http:
                iso = (await http.get(url)).content  # the installer reads the whole image
            if "kickstart-error" in self.faults:  # the installer rejects the script and reboots (live run 8)
                await self.esxi.reject_kickstart()
            else:
                await self.esxi.run_installer(iso)
        except Exception:
            logger.exception("Simulated installer failed")

    def _spawn(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)


def _error(status: int, message: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"message": message, "@Message.ExtendedInfo": [{"Message": message}]}}
    )
