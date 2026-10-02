"""The HTTPS media endpoint BMCs download installer ISOs from.

Deliberately tiny and separate from the API: it exposes only `/media/{token}/{filename}`, so it can
listen on a lab-reachable address while the API stays on localhost.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from groundzero.core.config import write_private
from groundzero.core.store import utcnow
from groundzero.media.registry import MediaFetch, MediaRegistry

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def _served_bytes(range_header: str | None, size: int) -> int:
    if not range_header:
        return size
    m = _RANGE.fullmatch(range_header.strip())
    if not m:
        return 0
    start, end = m.group(1), m.group(2)
    if not start:  # suffix range: last N bytes
        return min(int(end or 0), size)
    stop = min(int(end), size - 1) if end else size - 1
    return max(0, stop - int(start) + 1)


def create_media_app(registry: MediaRegistry) -> FastAPI:
    app = FastAPI(title="GroundZero media", openapi_url=None, docs_url=None, redoc_url=None)

    @app.api_route("/media/{token}/{filename}", methods=["GET", "HEAD"])
    def media(token: str, filename: str, request: Request) -> FileResponse:
        path = registry.resolve(token, filename)
        if path is None:
            raise HTTPException(status_code=404)
        range_header = request.headers.get("range")
        size = path.stat().st_size
        registry.record(
            token,
            MediaFetch(
                # ip:port, so the log shows whether the BMC reuses connections or opens one per read
                client=f"{request.client.host}:{request.client.port}" if request.client else "unknown",
                method=request.method,
                byte_range=range_header,
                bytes=0 if request.method == "HEAD" else _served_bytes(range_header, size),
                at=utcnow(),
            ),
        )
        return FileResponse(path, media_type="application/octet-stream", filename=filename)

    return app


def ensure_tls_certificate(directory: Path, addresses: list[str]) -> tuple[Path, Path]:
    """Self-signed certificate for the media listener (BMCs fetch over HTTPS; most do not validate)."""
    cert_path, key_path = directory / "media.crt", directory / "media.key"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path
    directory.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "GroundZero media")])
    sans: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for addr in addresses:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(addr)))
        except ValueError:
            sans.append(x509.DNSName(addr))
    now = utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .sign(key, hashes.SHA256())
    )
    write_private(
        key_path,
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ),
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
