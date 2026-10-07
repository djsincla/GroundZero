"""Deploy an OVA straight to a standalone ESXi host over the vSphere API (no ovftool). Blocking.

ImportVApp hands back an NFC lease with one upload URL per disk; each disk is streamed out of the OVA
(a tar) without unpacking it, with progress reported to the lease so it does not expire. Idempotent:
if a VM with the target name already exists it is left alone (and powered on), unless ``replace`` asks
for it to be deleted and deployed fresh (appliances apply their settings on first boot only).
"""

from __future__ import annotations

import logging
import ssl
import tarfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import httpx
from pydantic import BaseModel

from groundzero.esxi.reader import EsxiError
from groundzero.ova.descriptor import DescriptorError, environment_values, parse_descriptor, read_ova

logger = logging.getLogger(__name__)
CHUNK = 1024 * 1024


class OvaDeployResult(BaseModel):
    vm_name: str
    created: bool
    powered_on: bool
    uploaded_bytes: int = 0
    seconds: float = 0.0
    settings_applied: bool = True
    replaced: bool = False  # an existing VM of that name was deleted first
    message: str = ""


OVF_ENV_KEY = "guestinfo.ovfEnv"


def ovf_environment(properties: dict[str, str]) -> str:
    """The OVF environment an appliance reads at boot (``vmtoolsd --cmd 'info-get guestinfo.ovfEnv'``).

    A standalone ESXi host does not keep vApp properties from an import, so (like ovftool's
    --X:injectOvfEnv and the Host Client) the values are written into the VM as this document.
    """
    quote = {'"': "&quot;"}  # attribute values: a password may contain a double quote
    rows = "\n".join(
        f'    <Property oe:key="{escape(k, quote)}" oe:value="{escape(v, quote)}"/>'
        for k, v in properties.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Environment xmlns="http://schemas.dmtf.org/ovf/environment/1" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:oe="http://schemas.dmtf.org/ovf/environment/1" oe:id="">\n'
        "  <PlatformSection><Kind>VMware ESXi</Kind><Vendor>VMware, Inc.</Vendor><Locale>en</Locale>"
        "</PlatformSection>\n"
        f"  <PropertySection>\n{rows}\n  </PropertySection>\n"
        "</Environment>\n"
    )


def has_ovf_environment(vm: Any) -> bool:
    return any(o.key == OVF_ENV_KEY for o in (vm.config.extraConfig or []))


def inject_ovf_environment(vm: Any, properties: dict[str, str]) -> None:
    """Write the OVF environment into a powered-off VM (read by the guest on its next boot)."""
    import pyVmomi

    vim: Any = pyVmomi.vim
    spec = vim.vm.ConfigSpec(
        extraConfig=[vim.option.OptionValue(key=OVF_ENV_KEY, value=ovf_environment(properties))]
    )
    _wait_task(vm.ReconfigVM_Task(spec=spec))


def read_descriptor(ova: Path) -> tuple[str, dict[str, int]]:
    """The OVF descriptor and the size of every file in the OVA."""
    try:
        return read_ova(ova)
    except DescriptorError as exc:
        raise EsxiError(str(exc)) from exc


def qualify_properties(descriptor: str, properties: dict[str, str]) -> dict[str, str]:
    """Every property the OVA declares, keyed as the guest reads it (``<class>.<key>[.<instance>]``).

    Given values may use bare or qualified keys; the rest get their defaults. A property in
    ``<ProductSection ovf:class="network">`` is ``network.ip`` in the OVF environment, not ``ip`` (live
    finding: the Holorouter ignored bare keys and booted without an IP). Undeclared keys are an error.
    """
    try:
        return environment_values(parse_descriptor(descriptor), properties)
    except DescriptorError as exc:
        raise EsxiError(str(exc)) from exc


def _stream(ova: Path, member: str, sent: list[int], lock: threading.Lock) -> Iterator[bytes]:
    with tarfile.open(ova) as tar:
        handle = tar.extractfile(member)
        if handle is None:
            raise EsxiError(f"{member} not found in {ova.name}")
        while chunk := handle.read(CHUNK):
            with lock:
                sent[0] += len(chunk)
            yield chunk


def deploy_ova(
    host: Any,
    address: str,
    ova: Path,
    *,
    vm_name: str,
    datastore: str,
    networks: dict[str, str],
    properties: dict[str, str],
    ssl_context: ssl.SSLContext,
    progress: Callable[[float, str], None] = lambda f, m: None,
    power_on: bool = True,
    replace: bool = False,
) -> OvaDeployResult:
    """``networks`` maps the OVF network names to port groups; ``properties`` are OVF property values."""
    import pyVmomi

    vim: Any = pyVmomi.vim  # untyped library
    content = vim.ServiceInstance("ServiceInstance", host._stub).RetrieveContent()
    descriptor, sizes = read_descriptor(ova)
    properties = qualify_properties(descriptor, properties)
    datacenter = content.rootFolder.childEntity[0]
    existing = next(
        (vm for vm in datacenter.vmFolder.childEntity if getattr(vm, "name", None) == vm_name), None
    )
    if existing is not None and replace:
        # Appliances apply their OVF settings on first boot only: changing them means a fresh VM.
        if existing.runtime.powerState == "poweredOn":
            progress(0.02, f"Powering off {vm_name} to replace it")
            _wait_task(existing.PowerOffVM_Task())
        progress(0.04, f"Deleting {vm_name} to replace it")
        _wait_task(existing.Destroy_Task())
        replaced = True
    elif existing is not None:
        on = existing.runtime.powerState == "poweredOn"
        if not has_ovf_environment(existing):
            return OvaDeployResult(
                vm_name=vm_name,
                created=False,
                powered_on=on,
                settings_applied=False,
                message=f"{vm_name} exists without its settings, and an appliance applies them only on first "
                "boot; deploy again with replace to delete it and deploy it fresh",
            )
        if power_on and not on:
            _wait_task(existing.PowerOnVM_Task())
        return OvaDeployResult(
            vm_name=vm_name,
            created=False,
            powered_on=power_on or on,
            message=f"{vm_name} already exists; left as is",
        )
    else:
        replaced = False

    ds = next((d for d in host.datastore if d.summary.name == datastore), None)
    if ds is None:
        raise EsxiError(f"Datastore {datastore} not found on the host")
    by_name = {n.name: n for n in host.network}
    missing = sorted(pg for pg in networks.values() if pg not in by_name)
    if missing:
        raise EsxiError(f"Port group(s) not found on the host: {', '.join(missing)}")
    params = vim.OvfManager.CreateImportSpecParams(
        entityName=vm_name,
        diskProvisioning="thin",
        networkMapping=[
            vim.OvfManager.NetworkMapping(name=ovf_net, network=by_name[pg])
            for ovf_net, pg in networks.items()
        ],
        propertyMapping=[vim.KeyValue(key=k, value=v) for k, v in properties.items()],
    )
    spec = content.ovfManager.CreateImportSpec(descriptor, host.parent.resourcePool, ds, params)
    if spec.error:
        raise EsxiError("The OVA was rejected: " + "; ".join(e.localizedMessage for e in spec.error))
    for warning in spec.warning or []:
        logger.warning("OVF import warning: %s", warning.localizedMessage)

    lease = host.parent.resourcePool.ImportVApp(spec.importSpec, datacenter.vmFolder, host)
    deadline = time.monotonic() + 300
    while lease.state == vim.HttpNfcLease.State.initializing and time.monotonic() < deadline:
        time.sleep(1)
    if lease.state != vim.HttpNfcLease.State.ready:
        raise EsxiError(
            f"The upload lease did not become ready ({lease.state}): {getattr(lease, 'error', '')}"
        )

    files = {item.deviceId: item.path for item in spec.fileItem or []}
    uploads = [
        (files[d.importKey], d.url.replace("*", address))
        for d in lease.info.deviceUrl
        if d.importKey in files
    ]
    total = sum(sizes.get(path, 0) for path, _ in uploads) or 1
    sent, lock, done = [0], threading.Lock(), threading.Event()
    started = time.monotonic()

    def keepalive() -> None:  # the lease expires without progress updates
        while not done.wait(15):
            with lock:
                pct = int(sent[0] * 100 / total)
            try:
                lease.HttpNfcLeaseProgress(min(pct, 99))
            except Exception as exc:  # noqa: BLE001 - the upload itself will report the real failure
                logger.debug("Lease progress update failed: %s", exc)
            rate = sent[0] / max(time.monotonic() - started, 1)
            eta = (total - sent[0]) / rate if rate else 0
            done_gb, total_gb = sent[0] / 1e9, total / 1e9
            speed = f"{rate / 1e6:.2f} MB/s, ~{eta / 60:.0f} min left"
            message = f"Uploading {done_gb:.2f} of {total_gb:.2f} GB ({speed})"
            progress(0.1 + 0.8 * sent[0] / total, message)

    ticker = threading.Thread(target=keepalive, daemon=True)
    ticker.start()
    try:
        with httpx.Client(verify=ssl_context, timeout=httpx.Timeout(60, write=600)) as client:
            for path, url in uploads:
                resp = client.post(
                    url,
                    content=_stream(ova, path, sent, lock),
                    headers={
                        "Content-Type": "application/x-vnd.vmware-streamVmdk",
                        "Content-Length": str(sizes[path]),
                    },
                )
                if resp.status_code >= 300:
                    raise EsxiError(f"Upload of {path} failed: HTTP {resp.status_code} {resp.text[:200]}")
        vm = lease.info.entity  # read before completing: ESXi clears lease.info at completion
        lease.HttpNfcLeaseProgress(100)
        lease.HttpNfcLeaseComplete()
    except BaseException as exc:
        try:
            lease.HttpNfcLeaseAbort(vim.LocalizedMethodFault(localizedMessage=str(exc)[:200]))
        except Exception:
            logger.exception("Could not abort the upload lease")
        raise
    finally:
        done.set()
    progress(0.91, f"Writing {vm_name}'s settings (OVF environment)")
    inject_ovf_environment(vm, properties)
    if power_on:
        progress(0.92, f"Powering on {vm_name}")
        _wait_task(vm.PowerOnVM_Task())
    return OvaDeployResult(
        vm_name=vm_name,
        created=True,
        powered_on=power_on,
        uploaded_bytes=sent[0],
        seconds=round(time.monotonic() - started, 1),
        replaced=replaced,
    )


def _wait_task(task: Any, timeout: float = 600) -> None:
    deadline = time.monotonic() + timeout
    while task.info.state in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(1)
    if task.info.state != "success":
        raise EsxiError(f"Task failed: {getattr(task.info.error, 'localizedMessage', task.info.state)}")
