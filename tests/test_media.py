from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from groundzero.media.registry import MediaRegistry, media_url, source_address_towards
from groundzero.media.server import _served_bytes, create_media_app, ensure_tls_certificate

PAYLOAD = bytes(range(256)) * 64  # 16 KiB, distinct bytes so ranges are checkable


@pytest.fixture
def iso(tmp_path: Path) -> Path:
    path = tmp_path / "esxi1.iso"
    path.write_bytes(PAYLOAD)
    return path


@pytest.fixture
def registry() -> MediaRegistry:
    return MediaRegistry()


@pytest.fixture
def client(registry: MediaRegistry) -> TestClient:
    return TestClient(create_media_app(registry))


def test_full_and_range_downloads_are_logged(registry: MediaRegistry, client: TestClient, iso: Path) -> None:
    token = registry.publish(iso, timedelta(hours=1))
    url = f"/media/{token}/esxi1.iso"

    head = client.head(url)
    assert head.status_code == 200 and head.headers["accept-ranges"] == "bytes"
    assert int(head.headers["content-length"]) == len(PAYLOAD)

    full = client.get(url)
    assert full.status_code == 200 and full.content == PAYLOAD

    part = client.get(url, headers={"Range": "bytes=2048-4095"})
    assert part.status_code == 206 and part.content == PAYLOAD[2048:4096]
    assert part.headers["content-range"] == f"bytes 2048-4095/{len(PAYLOAD)}"

    stats = registry.stats(token)
    assert stats is not None
    assert stats.requests == 3 and stats.bytes_served == len(PAYLOAD) + 2048
    assert stats.clients == ["testclient"] and stats.size == len(PAYLOAD)


def test_unknown_wrong_name_expired_and_revoked_are_404(
    registry: MediaRegistry, client: TestClient, iso: Path
) -> None:
    assert client.get("/media/nope/esxi1.iso").status_code == 404
    token = registry.publish(iso, timedelta(hours=1))
    assert client.get(f"/media/{token}/other.iso").status_code == 404
    registry.revoke(token)
    assert client.get(f"/media/{token}/esxi1.iso").status_code == 404
    expired = registry.publish(iso, timedelta(seconds=-1))
    assert client.get(f"/media/{expired}/esxi1.iso").status_code == 404


def test_only_media_routes_are_exposed(client: TestClient) -> None:
    for path in ("/docs", "/openapi.json", "/api/v1/hosts", "/healthz"):
        assert client.get(path).status_code == 404


def test_tokens_are_unguessable(registry: MediaRegistry, iso: Path) -> None:
    tokens = {registry.publish(iso, timedelta(hours=1)) for _ in range(50)}
    assert len(tokens) == 50 and min(len(t) for t in tokens) >= 32


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, 1000),
        ("bytes=0-99", 100),
        ("bytes=900-", 100),
        ("bytes=-50", 50),
        ("bytes=990-5000", 10),
        ("junk", 0),
    ],
)
def test_served_bytes(header: str | None, expected: int) -> None:
    assert _served_bytes(header, 1000) == expected


def test_media_url_and_source_address() -> None:
    assert media_url("https://10.0.0.1/", "tok", "a.iso") == "https://10.0.0.1/media/tok/a.iso"
    assert source_address_towards("127.0.0.1") == "127.0.0.1"


def test_tls_certificate_created_once_with_private_key(tmp_path: Path) -> None:
    cert, key = ensure_tls_certificate(tmp_path / "tls", ["192.0.2.10"])
    assert key.stat().st_mode & 0o777 == 0o600
    first = cert.read_bytes()
    ensure_tls_certificate(tmp_path / "tls", [])
    assert cert.read_bytes() == first
