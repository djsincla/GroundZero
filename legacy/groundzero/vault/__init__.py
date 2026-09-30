"""
GroundZero — Optional Encrypted Local Credential Vault (groundzero.vault)

OFF BY DEFAULT.  Nothing here runs unless the user explicitly opts in via
``python -m groundzero.vault init``, ``groundzero_collector.py --vault``, or the
Web UI "Encrypted Credential Vault" card.

Layout:
    crypto.py      — stdlib-only PBKDF2 + HMAC-SHA256 Encrypt-then-MAC primitives
    store.py       — file format, atomic 0600 writes, entry management, resolver
    csv_import.py  — CSV text parser for bulk import
    __main__.py    — ``python -m groundzero.vault`` management commands

This package must never import ``groundzero.web``, ``compat_engine`` or ``bcg_links``.
"""

from groundzero.vault.crypto import VaultAuthError, VaultCryptoError
from groundzero.vault.csv_import import CSV_TEMPLATE, parse_credentials_csv
from groundzero.vault.providers import (
    BaseCredentialProvider,
    ChainedCredentialProvider,
    HashiCorpVaultProvider,
    LocalVaultProvider,
    SddcManagerSecretProvider,
)
from groundzero.vault.store import (
    DEFAULT_VAULT_PATH,
    MIN_PASSPHRASE_LEN,
    CredentialVault,
    VaultError,
    VaultExistsError,
    VaultFormatError,
    VaultNotFoundError,
    normalize_target,
)

__all__ = [
    "BaseCredentialProvider",
    "CSV_TEMPLATE",
    "ChainedCredentialProvider",
    "DEFAULT_VAULT_PATH",
    "HashiCorpVaultProvider",
    "LocalVaultProvider",
    "MIN_PASSPHRASE_LEN",
    "CredentialVault",
    "SddcManagerSecretProvider",
    "VaultAuthError",
    "VaultCryptoError",
    "VaultError",
    "VaultExistsError",
    "VaultFormatError",
    "VaultNotFoundError",
    "normalize_target",
    "parse_credentials_csv",
]
