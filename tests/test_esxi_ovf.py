"""OVA deploy: the OVF environment that carries an appliance's settings on standalone ESXi."""

from __future__ import annotations

import ssl
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace as NS
from typing import Any

import pytest

from groundzero.esxi import ovf

OE = "{http://schemas.dmtf.org/ovf/environment/1}"

# The Holorouter 9.1.1 descriptor (trimmed): properties in classed ProductSections.
DESCRIPTOR = (Path(__file__).parent / "fixtures" / "ova" / "holorouter-9.1.1.ovf").read_text()


def _ova(tmp_path: Path) -> Path:
    ovf_file = tmp_path / "holorouter.ovf"
    ovf_file.write_text(DESCRIPTOR)
    ova = tmp_path / "holorouter.ova"
    with tarfile.open(ova, "w") as tar:
        tar.add(ovf_file, arcname=ovf_file.name)
    return ova


def test_property_keys_are_qualified_by_their_section_class() -> None:
    """Regression (live): bare keys were ignored by the Holorouter, which booted without an IP."""
    full = ovf.qualify_properties(
        DESCRIPTOR, {"hostname": "holorouter", "ip": "192.0.2.150", "ssh_enabled": "True"}
    )
    assert {k: full[k] for k in ("network.hostname", "network.ip", "extra.ssh_enabled")} == {
        "network.hostname": "holorouter",
        "network.ip": "192.0.2.150",
        "extra.ssh_enabled": "True",
    }
    # every declared property reaches the guest: unset ones with their default (or empty), as vCenter does
    assert full["extra.webtop_enabled"] == "true" and full["network.dns_domain"] == ""
    assert ovf.qualify_properties(DESCRIPTOR, {"network.ip": "x"})["network.ip"] == "x"  # already qualified
    with pytest.raises(ovf.EsxiError, match="declares no property bogus"):
        ovf.qualify_properties(DESCRIPTOR, {"bogus": "1"})


def test_ovf_environment_carries_every_property_and_escapes_values() -> None:
    xml = ovf.ovf_environment({"ip": "192.0.2.150", "mask": "24", "password": 'VMware1!"<&'})
    root = ET.fromstring(xml)
    props = {p.get(f"{OE}key"): p.get(f"{OE}value") for p in root.iter(f"{OE}Property")}
    assert props == {"ip": "192.0.2.150", "mask": "24", "password": 'VMware1!"<&'}  # parses back intact


class FakeVm:
    def __init__(self, name: str, on: bool, env: bool) -> None:
        self.name = name
        self.runtime = NS(powerState="poweredOn" if on else "poweredOff")
        self.config = NS(extraConfig=[NS(key=ovf.OVF_ENV_KEY, value="<Environment/>")] if env else [])
        self.calls: list[str] = []

    def _task(self, name: str) -> Any:
        self.calls.append(name)
        return NS(info=NS(state="success"))

    def PowerOnVM_Task(self) -> Any:
        self.runtime.powerState = "poweredOn"
        return self._task("on")

    def PowerOffVM_Task(self) -> Any:
        self.runtime.powerState = "poweredOff"
        return self._task("off")

    def ReconfigVM_Task(self, spec: Any) -> Any:
        self.config.extraConfig = list(spec.extraConfig)
        return self._task("reconfig")


def _deploy(monkeypatch: Any, vm: FakeVm, tmp_path: Path, **kw: Any) -> ovf.OvaDeployResult:
    content = NS(rootFolder=NS(childEntity=[NS(vmFolder=NS(childEntity=[vm]))]))
    monkeypatch.setattr(ovf.time, "sleep", lambda s: None)

    class SI:
        def __init__(self, *_: Any) -> None: ...

        def RetrieveContent(self) -> Any:
            return content

    import pyVmomi

    monkeypatch.setattr(pyVmomi.vim, "ServiceInstance", SI)
    return ovf.deploy_ova(
        NS(_stub=None),
        "esxi",
        _ova(tmp_path),
        vm_name=vm.name,
        datastore="ds",
        networks={},
        properties={"ip": "192.0.2.150"},
        ssl_context=ssl.create_default_context(),
        **kw,
    )


def test_existing_vm_with_its_settings_is_left_alone(monkeypatch: Any, tmp_path: Path) -> None:
    vm = FakeVm("holo1-holorouter", on=True, env=True)
    result = _deploy(monkeypatch, vm, tmp_path)
    assert result.settings_applied and not result.created and vm.calls == []


def test_a_running_vm_without_settings_is_reported_not_touched(monkeypatch: Any, tmp_path: Path) -> None:
    """Regression (live): the Holorouter booted without IP; a re-run must say so, not pretend success."""
    vm = FakeVm("holo1-holorouter", on=True, env=False)
    result = _deploy(monkeypatch, vm, tmp_path)
    assert not result.settings_applied and "reapply" in result.message and vm.calls == []


def test_reapply_power_cycles_and_writes_the_settings(monkeypatch: Any, tmp_path: Path) -> None:
    vm = FakeVm("holo1-holorouter", on=True, env=False)
    result = _deploy(monkeypatch, vm, tmp_path, reapply=True)
    assert result.settings_applied and vm.calls == ["off", "reconfig", "on"]
    env = next(o.value for o in vm.config.extraConfig if o.key == ovf.OVF_ENV_KEY)
    assert 'oe:key="network.ip" oe:value="192.0.2.150"' in env  # qualified, as the guest reads it
