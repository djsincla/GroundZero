"""Image repository: a folder of stock images the user maintains (GroundZero never downloads).

ISOs are identified by the OS plugin that recognises them; OVAs (Holorouter, VCF Installer) by the
product in their OVF descriptor. The SHA-256 is cached by (path, size, mtime) so rescans are cheap.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tarfile
import threading
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from groundzero.core.config import write_private
from groundzero.core.store import utcnow
from groundzero.osconfig import PLUGINS

logger = logging.getLogger(__name__)


class IsoImage(BaseModel):
    id: str  # first 12 hex of the SHA-256: stable across renames/moves
    filename: str
    kind: str = "iso"  # "iso" or "ova"
    product: str | None = None  # e.g. "HoloRouter", "VMware VCF SDDC Manager Appliance"
    os_family: str | None  # esxi | holorouter | vcf-installer; None: not recognised
    version: str | None
    build: str | None
    size: int
    sha256: str
    modified_at: datetime


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class IsoRepository:
    def __init__(self, directory: Path, cache_file: Path) -> None:
        self.directory = directory
        self._cache_file = cache_file
        self._lock = threading.Lock()
        self._images: dict[str, tuple[IsoImage, Path]] = {}
        self._scanned = False

    def scan(self) -> list[IsoImage]:
        """Rescan the folder. Blocking (hashes new files); call via a thread from async code."""
        cache = self._load_cache()
        found: dict[str, tuple[IsoImage, Path]] = {}
        if self.directory.is_dir():
            for path in sorted(p for p in self.directory.iterdir() if p.suffix.lower() in (".iso", ".ova")):
                stat = path.stat()
                key = f"{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
                cached = cache.get(key)
                image = IsoImage.model_validate(cached) if cached else self._identify(path, stat.st_size)
                cache[key] = image.model_dump(mode="json")
                found[image.id] = (image, path)
        self._save_cache(
            {k: v for k, v in cache.items() if any(k.startswith(str(p.resolve())) for _, p in found.values())}
        )
        with self._lock:
            self._images = found
            self._scanned = True
        return self.list()

    def list(self) -> list[IsoImage]:
        """Known images; the first call scans the folder (after a restart nothing is known yet)."""
        if not self._scanned:
            return self.scan()
        with self._lock:
            return sorted((img for img, _ in self._images.values()), key=lambda i: i.filename)

    def resolve(self, iso_id: str) -> tuple[IsoImage, Path] | None:
        if not self._scanned:
            self.scan()
        with self._lock:
            return self._images.get(iso_id)

    def _identify(self, path: Path, size: int) -> IsoImage:
        sha = _sha256(path)
        family = version = build = product = None
        kind = "ova" if path.suffix.lower() == ".ova" else "iso"
        if kind == "ova":
            found = detect_ova(path)
            if found:
                product, family, version, build = found
        else:
            for plugin in PLUGINS.values():
                meta = plugin.detect_iso(path)
                if meta is not None:
                    family, version, build = plugin.family, meta.version, meta.build
                    break
        return IsoImage(
            id=sha[:12],
            filename=path.name,
            kind=kind,
            product=product,
            os_family=family,
            version=version,
            build=build,
            size=size,
            sha256=sha,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=utcnow().tzinfo),
        )

    def _load_cache(self) -> dict[str, dict[str, object]]:
        try:
            data: dict[str, dict[str, object]] = json.loads(self._cache_file.read_text())
            return data
        except (OSError, ValueError):
            return {}

    def _save_cache(self, cache: dict[str, dict[str, object]]) -> None:
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            write_private(self._cache_file, json.dumps(cache, indent=2).encode())
        except OSError:
            logger.warning("Could not write ISO cache %s", self._cache_file)


# OVF product name → image family. Holodeck needs the Holorouter and, for VCF 9, the VCF Installer
# (shipped as the "VCF SDDC Manager Appliance" OVA).
_OVA_FAMILIES = (
    ("holorouter", "holorouter"),
    ("sddc manager", "vcf-installer"),
    ("cloud builder", "vcf-installer"),
)


def detect_ova(path: Path) -> tuple[str, str | None, str | None, str | None] | None:
    """(product, family, version, build) from the OVF descriptor (the OVA's first member). Never raises."""
    try:
        with tarfile.open(path) as tar:
            first = tar.next()
            if first is None or not first.name.endswith(".ovf"):
                return None
            handle = tar.extractfile(first)
            ovf = handle.read(4_000_000).decode(errors="replace") if handle else ""
    except (OSError, tarfile.TarError):
        return None

    def tag(name: str) -> str | None:
        m = re.search(rf"<(?:ovf:)?{name}>([^<]*)<", ovf)
        return m.group(1).strip() if m else None

    product = tag("Product")
    if not product:
        return None
    family = next((f for key, f in _OVA_FAMILIES if key in product.lower()), None)
    version = tag("Version")
    build = None
    if full := tag("FullVersion"):
        m = re.search(r"Build_(\d+)", full) or re.search(r"(\d{5,})", full)
        build = m.group(1) if m else None
    # e.g. holorouter-9.1.1.0456.ova: version (and build) only in the file name
    if not version and (m := re.search(r"(\d+\.\d+\.\d+)(?:\.(\d+))?", path.name)):
        version, build = m.group(1), build or m.group(2)
    return product, family, version, build
