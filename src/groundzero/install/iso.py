"""Build an unattended ESXi installer ISO from the stock VMware ISO.

Changes made (and verified by re-reading the output):
- `/BOOT.CFG` (BIOS) and `/EFI/BOOT/BOOT.CFG` (UEFI): kernel options gain `ks=cdrom:/KS.CFG` (+ extras)
- `/KS.CFG` added
The El Torito boot catalog (BIOS + EFI images) is carried over unchanged.
"""

from __future__ import annotations

import contextlib
import io
import re
import struct
from dataclasses import dataclass
from pathlib import Path

import pycdlib
from pycdlib.dr import DirectoryRecord

BOOT_CFGS = ("/BOOT.CFG;1", "/EFI/BOOT/BOOT.CFG;1")
KICKSTART_PATH = "/KS.CFG;1"


class IsoBuildError(Exception):
    error_type = "iso_build_failed"


@dataclass(frozen=True)
class IsoInfo:
    version: str | None
    build: str | None
    kernel_options: str


def _read(iso: pycdlib.PyCdlib, path: str) -> str:
    buf = io.BytesIO()
    iso.get_file_from_iso_fp(buf, iso_path=path)
    return buf.getvalue().decode()


def _replace(iso: pycdlib.PyCdlib, path: str, content: str) -> None:
    data = content.encode()
    iso.rm_file(iso_path=path)
    iso.add_fp(io.BytesIO(data), len(data), iso_path=path)


def patch_boot_cfg(text: str, extra_options: list[str]) -> str:
    """Append options to the kernelopt line, without duplicating ones already present."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("kernelopt="):
            current = line.removeprefix("kernelopt=").split()
            current += [opt for opt in extra_options if opt not in current]
            lines[i] = "kernelopt=" + " ".join(current)
            return "\n".join(lines) + "\n"
    raise IsoBuildError("boot.cfg has no kernelopt line")


def inspect_iso(path: Path) -> IsoInfo:
    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    try:
        cfg = _read(iso, BOOT_CFGS[1])
        kernelopt = next(
            (ln.removeprefix("kernelopt=") for ln in cfg.splitlines() if ln.startswith("kernelopt=")), ""
        )
        version = build = None
        try:
            discinfo = _read(iso, "/.DISCINFO;1")
            m = re.search(r"Version:\s*(\d+\.\d+\.\d+)-\d+\.(\d+)", discinfo)  # e.g. 9.1.1-0.25714478
            if m:
                version, build = m.group(1), m.group(2)
        except pycdlib.pycdlibexception.PyCdlibInvalidInput:
            pass
        if build is None:  # fall back to the stock file name convention ...-9.1.1.0.25714478.x86_64.iso
            m = re.search(r"-(\d+\.\d+\.\d+)(?:\.\d+)?\.(\d{6,})", path.name)
            if m:
                version, build = version or m.group(1), m.group(2)
        return IsoInfo(version=version, build=build, kernel_options=kernelopt)
    finally:
        iso.close()


def build_install_iso(stock_iso: Path, output: Path, kickstart: str, kernel_options: list[str]) -> None:
    if not stock_iso.is_file():
        raise IsoBuildError(f"Stock ISO not found: {stock_iso}")
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(".partial")
    iso = pycdlib.PyCdlib()
    try:
        iso.open(str(stock_iso))
        if iso.eltorito_boot_catalog is None:
            raise IsoBuildError("Stock ISO is not bootable (no El Torito catalog)")
        for cfg in BOOT_CFGS:
            _replace(iso, cfg, patch_boot_cfg(_read(iso, cfg), kernel_options))
        with contextlib.suppress(pycdlib.pycdlibexception.PyCdlibInvalidInput):  # no KS.CFG yet
            iso.rm_file(iso_path=KICKSTART_PATH)
        ks = kickstart.encode()
        iso.add_fp(io.BytesIO(ks), len(ks), iso_path=KICKSTART_PATH)
        iso.write(str(tmp))
    except pycdlib.pycdlibexception.PyCdlibException as exc:
        raise IsoBuildError(f"Could not build ISO: {exc}") from exc
    finally:
        iso.close()
    verify_install_iso(tmp, kickstart, kernel_options)
    tmp.replace(output)


def verify_install_iso(path: Path, kickstart: str, kernel_options: list[str]) -> None:
    iso = pycdlib.PyCdlib()
    iso.open(str(path))
    try:
        if iso.eltorito_boot_catalog is None:
            raise IsoBuildError("Built ISO lost its El Torito boot catalog")
        _verify_boot_entries(iso, path)
        if _read(iso, KICKSTART_PATH) != kickstart:
            raise IsoBuildError("KS.CFG in the built ISO does not match the rendered kickstart")
        for cfg in BOOT_CFGS:
            opts = next(ln for ln in _read(iso, cfg).splitlines() if ln.startswith("kernelopt=")).split()
            missing = [o for o in kernel_options if o not in opts]
            if missing:
                raise IsoBuildError(f"{cfg} is missing kernel options {missing}")
    finally:
        iso.close()


def _verify_boot_entries(iso: pycdlib.PyCdlib, path: Path) -> None:
    """Each El Torito entry must point at its image; ISOLINUX's boot-info-table must match its new place."""
    catalog = iso.eltorito_boot_catalog
    if catalog is None:
        raise IsoBuildError("ISO has no El Torito boot catalog")
    entries = [catalog.initial_entry] + [e for sec in catalog.sections for e in sec.section_entries]
    images: dict[str, DirectoryRecord] = {}
    for name in ("/ISOLINUX.BIN;1", "/EFIBOOT.IMG;1"):
        try:
            record = iso.get_record(iso_path=name)
        except pycdlib.pycdlibexception.PyCdlibInvalidInput:
            continue
        if isinstance(record, DirectoryRecord):
            images[name] = record
    locations = {rec.extent_location() for rec in images.values()}
    for entry in entries:
        if entry.load_rba not in locations:
            raise IsoBuildError(f"El Torito entry points at sector {entry.load_rba}, which is no boot image")
    isolinux = images.get("/ISOLINUX.BIN;1")
    if isolinux is None:
        return
    with path.open("rb") as fh:
        fh.seek(isolinux.extent_location() * 2048)
        data = fh.read(isolinux.data_length)
    _pvd, file_lba, length, checksum = struct.unpack("<IIII", data[8:24])
    words = (len(data) - 64) // 4
    expected = sum(struct.unpack(f"<{words}I", data[64 : 64 + words * 4])) & 0xFFFFFFFF
    if (file_lba, length, checksum) != (isolinux.extent_location(), isolinux.data_length, expected):
        raise IsoBuildError("ISOLINUX boot-info-table does not match its location in the built ISO")
