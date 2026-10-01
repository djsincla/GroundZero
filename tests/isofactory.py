"""Builds small bootable ISOs shaped like the VMware ESXi installer (BIOS + EFI El Torito, BOOT.CFGs)."""

from __future__ import annotations

import io
from pathlib import Path

import pycdlib

STOCK_CFG = "\n".join(
    [
        "bootstate=0",
        "title=Loading ESXi installer",
        "kernel=/b.b00",
        "kernelopt=runweasel cdromBoot",
        "modules=/k.b00",
        "",
    ]
)


def _add(iso: pycdlib.PyCdlib, path: str, data: bytes) -> None:
    iso.add_fp(io.BytesIO(data), len(data), iso_path=path)


def make_stock_iso(path: Path, version: str = "9.1.1-0.25714478", payload_kib: int = 256) -> Path:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=4)  # allows the leading-dot .DISCINFO name used by the real ISO
    _add(iso, "/.DISCINFO;1", f"ESXi\nVersion: {version}\n".encode())
    iso.add_directory("/EFI")
    iso.add_directory("/EFI/BOOT")
    _add(iso, "/BOOT.CFG;1", STOCK_CFG.encode())
    _add(iso, "/EFI/BOOT/BOOT.CFG;1", STOCK_CFG.encode())
    _add(iso, "/ISOLINUX.BIN;1", b"\xeb\x3c" + b"\x00" * (7 * 2048 - 2))
    _add(iso, "/EFIBOOT.IMG;1", b"EFI" * 1000)
    _add(iso, "/IMGPAYLD.TGZ;1", bytes(range(256)) * 4 * payload_kib)  # stands in for the real payload
    iso.add_eltorito("/ISOLINUX.BIN;1", bootcatfile="/BOOT.CAT;1", boot_info_table=True, media_name="noemul")
    iso.add_eltorito("/EFIBOOT.IMG;1", efi=True, media_name="noemul")
    path.parent.mkdir(parents=True, exist_ok=True)
    iso.write(str(path))
    iso.close()
    return path
