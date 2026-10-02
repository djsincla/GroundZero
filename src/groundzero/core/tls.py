"""Certificate pinning (trust on first use) for BMCs and installed OSes.

Lab BMCs and ESXi hosts use self-signed certificates, so CA validation is not possible. Instead the
first certificate seen is recorded, and every later connection trusts *only* that certificate: if it
changes, the TLS handshake fails before any credential is sent.
"""

from __future__ import annotations

import hashlib
import ssl
from datetime import datetime

from pydantic import BaseModel


class CertificateChangedError(Exception):
    error_type = "certificate_changed"

    def __init__(self, role: str, address: str, pinned: str, seen: str | None) -> None:
        self.role, self.address, self.pinned, self.seen = role, address, pinned, seen
        observed = f"now presents {seen[:23]}…" if seen else "could not be verified against the pin"
        super().__init__(
            f"The {role} at {address} {observed}, but {pinned[:23]}… is pinned. No credentials were sent. "
            "If the certificate legitimately changed (e.g. reinstall, renewed cert), re-trust it."
        )


class PinnedCertificate(BaseModel):
    role: str  # "bmc" | "os"
    address: str
    fingerprint: str  # SHA-256, colon-separated hex
    pinned_at: datetime


def split_address(address: str, default_port: int = 443) -> tuple[str, int]:
    host, sep, port = address.rpartition(":")
    if sep and port.isdigit() and ":" not in host:  # host:port (not a bare IPv6 address)
        return host, int(port)
    return address, default_port


def fingerprint(pem: str) -> str:
    digest = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def fetch_certificate(address: str, timeout: float = 10.0) -> str:
    """The server's leaf certificate (PEM). Handshake only: nothing is sent to the server."""
    return ssl.get_server_certificate(split_address(address), timeout=timeout)


def pinned_context(pem: str) -> ssl.SSLContext:
    """A TLS context that trusts exactly this (usually self-signed) certificate, ignoring hostnames."""
    ctx = ssl.create_default_context(cadata=pem)
    ctx.check_hostname = False  # pinning replaces name checks; BMCs are addressed by IP
    ctx.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN  # accept the pinned leaf itself as trust anchor
    return ctx


def check_pin(role: str, address: str, pinned_pem: str, timeout: float = 10.0) -> None:
    """Fail fast with a clear error if the server no longer presents the pinned certificate."""
    try:
        seen = fetch_certificate(address, timeout)
    except OSError:
        return  # unreachable: the real connection will report it
    if fingerprint(seen) != fingerprint(pinned_pem):
        raise CertificateChangedError(role, address, fingerprint(pinned_pem), fingerprint(seen))
