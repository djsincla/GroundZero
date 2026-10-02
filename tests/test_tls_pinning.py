"""Certificate pinning against real local TLS servers whose certificate can be swapped."""

from __future__ import annotations

import socket
import ssl
import threading
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from groundzero.core.config import Settings
from groundzero.core.credentials import CredentialCipher
from groundzero.core.jobs import JobRunner
from groundzero.core.services import Services
from groundzero.core.store import Store, utcnow
from groundzero.core.tls import (
    CertificateChangedError,
    check_pin,
    fetch_certificate,
    fingerprint,
    pinned_context,
)


def _self_signed(tmp: Path, name: str) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(utcnow() - timedelta(days=1))
        .not_valid_after(utcnow() + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp / f"{name}.crt", tmp / f"{name}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return cert_path, key_path


class TlsServer:
    """Accepts TLS handshakes with whichever certificate is currently loaded."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.address = f"127.0.0.1:{self.sock.getsockname()[1]}"
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        threading.Thread(target=self._serve, daemon=True).start()

    def use(self, cert: Path, key: Path) -> None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.ctx = ctx

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                with self.ctx.wrap_socket(conn, server_side=True):
                    pass
            except (ssl.SSLError, OSError):
                pass


@pytest.fixture
def server(tmp_path: Path) -> Iterator[tuple[TlsServer, tuple[Path, Path], tuple[Path, Path]]]:
    a, b = _self_signed(tmp_path, "idrac-a"), _self_signed(tmp_path, "idrac-b")
    srv = TlsServer()
    srv.use(*a)
    yield srv, a, b
    srv.sock.close()


def _handshake(address: str, ctx: ssl.SSLContext) -> None:
    host, port = address.split(":")
    with socket.create_connection((host, int(port)), timeout=5) as s, ctx.wrap_socket(s):
        pass


def test_pinned_context_trusts_only_the_pinned_certificate(
    server: tuple[TlsServer, tuple[Path, Path], tuple[Path, Path]],
) -> None:
    srv, _, b = server
    pem = fetch_certificate(srv.address)
    _handshake(srv.address, pinned_context(pem))  # accepted
    srv.use(*b)
    with pytest.raises(ssl.SSLCertVerificationError):
        _handshake(srv.address, pinned_context(pem))  # a different certificate fails the handshake itself


def test_check_pin_reports_both_fingerprints(
    server: tuple[TlsServer, tuple[Path, Path], tuple[Path, Path]],
) -> None:
    srv, _, b = server
    pem = fetch_certificate(srv.address)
    check_pin("bmc", srv.address, pem)  # unchanged: no error
    srv.use(*b)
    with pytest.raises(CertificateChangedError) as err:
        check_pin("bmc", srv.address, pem)
    assert fingerprint(pem)[:23] in str(err.value) and "No credentials were sent" in str(err.value)


def test_trust_on_first_use_then_refuse_then_retrust(
    tmp_path: Path, server: tuple[TlsServer, tuple[Path, Path], tuple[Path, Path]]
) -> None:
    srv, _, b = server
    settings = Settings(home=tmp_path / "home", api_token="t")
    settings.ensure_home()
    store = Store(settings.db_path)
    services = Services(settings, store, JobRunner(store, 1), CredentialCipher(settings))
    from groundzero.core.models import HostCreate

    host = services.add_host(HostCreate(bmc_address=srv.address, username="root", password="pw"))  # type: ignore[arg-type]
    first = services.pinned_pem(host.id, "bmc", srv.address)
    assert first is not None and services.list_pins(host.id)[0].fingerprint == fingerprint(first)
    assert services.pinned_pem(host.id, "bmc", srv.address) == first  # pinned, not re-fetched

    srv.use(*b)
    with pytest.raises(CertificateChangedError):
        services.pinned_pem(host.id, "bmc", srv.address)

    renewed = services.retrust(host.id, "bmc")
    assert renewed.fingerprint != fingerprint(first)
    assert services.pinned_pem(host.id, "bmc", srv.address) is not None  # the new pin is accepted
    assert services.pinned_pem(host.id, "bmc", srv.address, verify_tls=True) is None  # CA mode: no pinning
