"""
GroundZero — Credential Vault cryptographic primitives (groundzero.vault.crypto)

Pure standard-library authenticated encryption for the optional local
credential vault.  This module performs NO file or network I/O.

Why not AES?
    The Python standard library ships no AES implementation, and this project
    is stdlib-only by hard constraint.  A pure-Python AES was deliberately
    rejected (timing side channels, large attack surface).  Instead the vault
    uses an Encrypt-then-MAC construction built exclusively from OpenSSL-backed
    primitives exposed via ``hashlib`` / ``hmac`` / ``secrets``:

    * Key derivation : PBKDF2-HMAC-SHA256, 600,000 iterations, 16-byte random salt
    * Sub-keys       : HMAC-SHA256(master, label) for the encryption and MAC keys
    * Confidentiality: keystream = HMAC-SHA256(enc_key, nonce || counter) in
                       counter mode, XORed with the plaintext (a PRF-based
                       stream cipher; a fresh 16-byte random nonce per encryption)
    * Integrity      : tag = HMAC-SHA256(mac_key, aad || nonce || ciphertext),
                       verified with ``hmac.compare_digest`` BEFORE decryption

    This is the same shape as Fernet (encrypt-then-MAC with separately derived
    keys), minus AES.  Do not describe it as AES anywhere.

Security notes:
    * The nonce MUST never repeat under the same key.  16 random bytes from
      ``secrets.token_bytes`` gives a negligible collision probability for the
      handful of saves a vault sees in its lifetime.
    * Callers must treat ``VaultAuthError`` as "wrong passphrase OR tampered
      file" and must not distinguish the two to the user.
"""

import hashlib
import hmac
import secrets
import struct
from typing import Tuple

PBKDF2_ITERATIONS = 600_000
SALT_LEN = 16
NONCE_LEN = 16
KEY_LEN = 32
TAG_LEN = 32

KDF_NAME = "pbkdf2-hmac-sha256"
CIPHER_NAME = "hmac-sha256-ctr+hmac-sha256-etm"

_ENC_LABEL = b"vcf-vault-enc-v1"
_MAC_LABEL = b"vcf-vault-mac-v1"


class VaultCryptoError(Exception):
    """Base class for vault cryptographic failures."""


class VaultAuthError(VaultCryptoError):
    """Authentication failed: wrong passphrase or tampered data."""


def new_salt() -> bytes:
    """Return a fresh random KDF salt."""
    return secrets.token_bytes(SALT_LEN)


def derive_master_key(passphrase: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    """Derive the 32-byte master key from a passphrase and salt (PBKDF2-HMAC-SHA256)."""
    if not isinstance(passphrase, str):
        raise VaultCryptoError("passphrase must be a str")
    if len(salt) < 8:
        raise VaultCryptoError("salt too short")
    if iterations < 100_000:
        raise VaultCryptoError("iteration count below safety floor")
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations, dklen=KEY_LEN)


def _subkey(master: bytes, label: bytes) -> bytes:
    return hmac.new(master, label, hashlib.sha256).digest()


def _keystream(enc_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    ctr = 0
    while len(out) < length:
        out += hmac.new(enc_key, nonce + struct.pack(">Q", ctr), hashlib.sha256).digest()
        ctr += 1
    return bytes(out[:length])


def _xor(a: bytes, b: bytes) -> bytes:
    if not a:
        return b""
    return (int.from_bytes(a, "big") ^ int.from_bytes(b, "big")).to_bytes(len(a), "big")


def _check_master(master: bytes) -> None:
    if not isinstance(master, (bytes, bytearray)) or len(master) != KEY_LEN:
        raise VaultCryptoError("master key must be %d bytes" % KEY_LEN)


def encrypt(master: bytes, plaintext: bytes, aad: bytes) -> Tuple[bytes, bytes, bytes]:
    """Encrypt-then-MAC.  Returns ``(nonce, ciphertext, tag)``.

    ``aad`` (additional authenticated data) is bound into the tag but not
    encrypted; the vault passes its serialized header so header tampering
    (e.g. lowering the KDF iteration count) is detected.
    """
    _check_master(master)
    nonce = secrets.token_bytes(NONCE_LEN)
    ct = _xor(bytes(plaintext), _keystream(_subkey(master, _ENC_LABEL), nonce, len(plaintext)))
    tag = hmac.new(_subkey(master, _MAC_LABEL), bytes(aad) + nonce + ct, hashlib.sha256).digest()
    return nonce, ct, tag


def decrypt(master: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, aad: bytes) -> bytes:
    """Verify the tag in constant time, then decrypt.  Raises ``VaultAuthError`` on mismatch."""
    _check_master(master)
    if len(nonce) != NONCE_LEN or len(tag) != TAG_LEN:
        raise VaultAuthError("authentication failed")
    expected = hmac.new(_subkey(master, _MAC_LABEL), bytes(aad) + bytes(nonce) + bytes(ciphertext), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, bytes(tag)):
        raise VaultAuthError("authentication failed")
    return _xor(bytes(ciphertext), _keystream(_subkey(master, _ENC_LABEL), bytes(nonce), len(ciphertext)))
