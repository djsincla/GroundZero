"""ISO repository: a folder of stock installer ISOs the user maintains (GroundZero never downloads).

Each ISO is identified by the OS plugin that recognises it (family, version, build); the SHA-256 is
cached by (path, size, mtime) so rescans are cheap.
"""

from __future__ import annotations

import hashlib
import json
import logging
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
    os_family: str | None  # None: no plugin recognises it
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
            for path in sorted(self.directory.glob("*.iso")):
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
        family = version = build = None
        for plugin in PLUGINS.values():
            meta = plugin.detect_iso(path)
            if meta is not None:
                family, version, build = plugin.family, meta.version, meta.build
                break
        return IsoImage(
            id=sha[:12],
            filename=path.name,
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
