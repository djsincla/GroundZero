"""Encryption of stored BMC credentials (Fernet, key file readable only by the owner)."""

from __future__ import annotations

from cryptography.fernet import Fernet

from groundzero.core.config import Settings, write_private


class CredentialCipher:
    def __init__(self, settings: Settings) -> None:
        settings.ensure_home()
        if settings.key_path.exists():
            key = settings.key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            write_private(settings.key_path, key)
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, token: bytes) -> str:
        return self._fernet.decrypt(token).decode()
