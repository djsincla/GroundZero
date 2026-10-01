"""Published installer media: unguessable, expiring URLs plus a log of who fetched what.

A BMC cannot send GroundZero's bearer token, so each published file gets a random URL token
instead. The fetch log lets an install job confirm the BMC is actually reading the ISO.
"""

from __future__ import annotations

import secrets
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from groundzero.core.store import utcnow


class MediaFetch(BaseModel):
    client: str
    method: str
    byte_range: str | None
    bytes: int
    at: datetime


class MediaStats(BaseModel):
    token: str
    filename: str
    size: int
    requests: int
    bytes_served: int
    clients: list[str]
    first_fetch: datetime | None
    last_fetch: datetime | None
    expires_at: datetime


@dataclass
class _Entry:
    path: Path
    filename: str
    expires_at: datetime
    fetches: list[MediaFetch] = field(default_factory=list)


class MediaRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def publish(self, path: Path, ttl: timedelta, filename: str | None = None) -> str:
        if not path.is_file():
            raise FileNotFoundError(path)
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._entries[token] = _Entry(path, filename or path.name, utcnow() + ttl)
        return token

    def revoke(self, token: str) -> None:
        with self._lock:
            self._entries.pop(token, None)

    def resolve(self, token: str, filename: str) -> Path | None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None or entry.filename != filename:
                return None
            if entry.expires_at <= utcnow():
                self._entries.pop(token, None)
                return None
            return entry.path

    def record(self, token: str, fetch: MediaFetch) -> None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is not None:
                entry.fetches.append(fetch)

    def stats(self, token: str) -> MediaStats | None:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None:
                return None
            fetches = list(entry.fetches)
        return MediaStats(
            token=token,
            filename=entry.filename,
            size=entry.path.stat().st_size,
            requests=len(fetches),
            bytes_served=sum(f.bytes for f in fetches),
            clients=sorted({f.client for f in fetches}),
            first_fetch=fetches[0].at if fetches else None,
            last_fetch=fetches[-1].at if fetches else None,
            expires_at=entry.expires_at,
        )


def media_url(base_url: str, token: str, filename: str) -> str:
    return f"{base_url.rstrip('/')}/media/{token}/{filename}"


def source_address_towards(target_host: str) -> str:
    """The local IP this machine would use to reach ``target_host`` (no packets are sent)."""
    host = target_host.rsplit(":", 1)[0] if target_host.count(":") == 1 else target_host
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((host, 443))
        return str(sock.getsockname()[0])
