from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pycdlib
import pytest
from isofactory import STOCK_CFG, make_stock_iso
from pydantic import ValidationError

from groundzero.install.crypt import sha512_crypt
from groundzero.install.iso import IsoBuildError, build_install_iso, inspect_iso, patch_boot_cfg
from groundzero.install.kickstart import render_kickstart
from groundzero.install.spec import InstallSpec, ManagementNetwork

BOSS = "t10.ATA_____DELLBOSS_VD_____________________________6b82d07b9f4d001000000000"


def _spec(**overrides: object) -> InstallSpec:
    data: dict[str, object] = {
        "install_disk": BOSS,
        "allow_legacy_cpu": True,
        "root_password_hash": sha512_crypt("secret", "fixedsalt"),
        "network": ManagementNetwork(
            hostname="esxi1",
            ip="192.0.2.101",
            netmask="255.255.255.0",
            gateway="192.0.2.1",
            nameservers=["8.8.8.8"],
            vlan_id=100,
            install_nic="vmnic0",
            extra_uplinks=["vmnic1"],
        ),
        "ntp_servers": ["pool.ntp.org"],
    }
    data.update(overrides)
    return InstallSpec.model_validate(data)


# ── crypt ────────────────────────────────────────────────────────────────
def test_sha512_crypt_reference_vectors() -> None:
    """Vectors from the SHA-crypt specification."""
    assert sha512_crypt("Hello world!", "saltstring") == (
        "$6$saltstring$svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1"
    )
    assert sha512_crypt("Hello world!", "saltstringsaltstring", rounds=10000) == (
        "$6$rounds=10000$saltstringsaltst$OW1/O6BYHV6BcXZu8QVeXbDWra3Oeqh0sbHbbMCVNSnCM/UrjmM0Dp8vOuZeHBy/YTBmSK6H9qs/y3RnOaw5v."
    )


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_sha512_crypt_matches_openssl() -> None:
    for pw, salt in [("p@ss w0rd!", "abcdefgh"), ("x" * 70, "0123456789abcdef")]:
        ref = subprocess.run(["openssl", "passwd", "-6", "-salt", salt, pw], capture_output=True, text=True)
        assert sha512_crypt(pw, salt) == ref.stdout.strip()


def test_random_salt_differs() -> None:
    assert sha512_crypt("same") != sha512_crypt("same")


# ── kickstart ────────────────────────────────────────────────────────────
def test_kickstart_for_lab_spec() -> None:
    ks = render_kickstart(_spec())
    assert (
        f"install --disk={BOSS} --preservevmfs "
        "--forceunsupportedinstall --ignoreprereqwarnings --ignoreprereqerrors"
    ) in ks
    assert "rootpw --iscrypted $6$fixedsalt$" in ks and "secret" not in ks
    assert (
        "network --bootproto=static --device=vmnic0 --ip=192.0.2.101 --netmask=255.255.255.0 "
        "--gateway=192.0.2.1 --nameserver=8.8.8.8 --hostname=esxi1 --vlanid=100"
    ) in ks
    assert "%post --interpreter=busybox --ignorefailure=true" in ks and "allowLegacyCPU=true" in ks
    firstboot = ks.split("%firstboot --interpreter=busybox\n")[1]
    assert firstboot.splitlines() == [
        "esxcli network vswitch standard uplink add -u vmnic1 -v vSwitch0",
        "esxcli network vswitch standard portgroup policy failover set"
        ' -p "Management Network" -a vmnic0,vmnic1',
        "esxcli system ntp set --server=pool.ntp.org --enabled=true",
    ]


def test_wipe_only_when_asked_and_no_cpu_override_by_default() -> None:
    ks = render_kickstart(_spec(preserve_vmfs=False, allow_legacy_cpu=False))
    assert "--overwritevmfs" in ks and "--preservevmfs" not in ks
    assert "allowLegacyCPU" not in ks and "ignoreprereq" not in ks and "forceunsupported" not in ks


@pytest.mark.parametrize(
    "field,value",
    [
        ("hostname", "esxi1; reboot"),
        ("ip", "192.0.2.999"),
        ("install_nic", "vmnic0 --ip=1.2.3.4"),
        ("nameservers", ["8.8.8.8 --x"]),
    ],
)
def test_network_spec_rejects_injection(field: str, value: object) -> None:
    net = _spec().network.model_dump()
    net[field] = value
    with pytest.raises(ValidationError):
        ManagementNetwork.model_validate(net)


def test_spec_rejects_bad_disk_ntp_and_plaintext_password() -> None:
    for bad in ({"install_disk": "disk; rm -rf /"}, {"ntp_servers": ["pool.ntp.org\nreboot"]},
                {"root_password_hash": "plaintext"}):  # fmt: skip
        with pytest.raises(ValidationError):
            _spec(**bad)


# ── ISO ──────────────────────────────────────────────────────────────────
@pytest.fixture
def stock_iso(tmp_path: Path) -> Path:
    return make_stock_iso(tmp_path / "VMware-VMvisor-Installer-9.1.1.0.25714478.x86_64.iso")


def test_build_install_iso(stock_iso: Path, tmp_path: Path) -> None:
    spec = _spec()
    ks = render_kickstart(spec)
    out = tmp_path / "out" / "esxi1.iso"
    build_install_iso(stock_iso, out, ks, spec.kernel_options)

    info = inspect_iso(out)
    assert (info.version, info.build) == ("9.1.1", "25714478")  # from .DISCINFO
    assert info.kernel_options == "runweasel cdromBoot ks=cdrom:/KS.CFG allowLegacyCPU=true"
    iso = pycdlib.PyCdlib()
    iso.open(str(out))
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path="/KS.CFG;1")
    iso.close()
    assert buf.getvalue().decode() == ks
    assert not out.with_suffix(".partial").exists()


def test_rebuilding_is_idempotent(stock_iso: Path, tmp_path: Path) -> None:
    spec = _spec()
    first, second = tmp_path / "a.iso", tmp_path / "b.iso"
    build_install_iso(stock_iso, first, render_kickstart(spec), spec.kernel_options)
    build_install_iso(first, second, render_kickstart(spec), spec.kernel_options)  # build from a built ISO
    assert inspect_iso(second).kernel_options.count("ks=cdrom:/KS.CFG") == 1


def test_patch_boot_cfg() -> None:
    patched = patch_boot_cfg(STOCK_CFG, ["ks=cdrom:/KS.CFG", "cdromBoot"])
    assert "kernelopt=runweasel cdromBoot ks=cdrom:/KS.CFG\n" in patched
    with pytest.raises(IsoBuildError):
        patch_boot_cfg("kernel=/b.b00\n", ["x"])


def test_non_bootable_or_missing_iso_rejected(tmp_path: Path) -> None:
    with pytest.raises(IsoBuildError, match="not found"):
        build_install_iso(tmp_path / "missing.iso", tmp_path / "o.iso", "ks", [])
    plain = pycdlib.PyCdlib()
    plain.new()
    plain.write(str(tmp_path / "plain.iso"))
    plain.close()
    with pytest.raises(IsoBuildError, match="not bootable"):
        build_install_iso(tmp_path / "plain.iso", tmp_path / "o.iso", "ks", [])
