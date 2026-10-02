"""Runtime settings. Every value can be overridden with a GROUNDZERO_* environment variable."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Values also load from a local, git-ignored .env file (e.g. lab BMC credentials).
    model_config = SettingsConfigDict(env_prefix="GROUNDZERO_", env_file=".env", extra="ignore")

    home: Path = Path.home() / ".groundzero"
    bind_host: str = "127.0.0.1"
    port: int = 7182
    max_concurrent_jobs: int = 4
    redfish_timeout: float = 30.0
    redfish_max_parallel: int = 4
    redfish_action_timeout: float = 180.0  # BMC actions such as InsertMedia can take minutes
    api_token: str | None = None
    bmc_username: str | None = None
    bmc_password: SecretStr | None = None
    # Simulation mode: serve every BMC from a recorded capture directory instead of the network.
    # Used for demos and black-box functional tests; reported by /healthz as mode "simulated".
    simulate_bmc_dir: Path | None = None
    # Same idea for the installed OS: a simulated ESXi from a capture dir (network/storage/about.json).
    simulate_esxi_dir: Path | None = None
    simulate_faults: list[str] = []  # simulator fault injection, e.g. ["ignore-boot-once"]
    install_poll_seconds: float = 20.0
    media_settle_seconds: float = 10.0  # extra pause after the media reports attached, before reset
    media_attach_seconds: float = 600.0  # max wait for mounted media to attach (lab preference: up to 10 min)
    media_cleanup_watch_seconds: float = 90.0  # after a failed mount, watch for a late attach to eject
    installer_boot_minutes: float = 20.0
    # HTTPS listener BMCs download installer ISOs from (must be reachable from the BMC network).
    media_bind_host: str = "0.0.0.0"
    media_port: int = 443
    media_public_url: str | None = None  # e.g. https://203.0.113.124; default: auto-detect per BMC
    esxi_username: str | None = None
    esxi_password: SecretStr | None = None

    @property
    def db_path(self) -> Path:
        return self.home / "groundzero.sqlite3"

    @property
    def token_path(self) -> Path:
        return self.home / "api-token"

    @property
    def media_dir(self) -> Path:
        return self.home / "media"

    @property
    def key_path(self) -> Path:
        return self.home / "secret.key"

    def ensure_home(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.home.chmod(0o700)

    def resolve_api_token(self) -> str:
        """Return the API token, generating and persisting one on first use."""
        if self.api_token:
            return self.api_token
        self.ensure_home()
        if self.token_path.exists():
            return self.token_path.read_text().strip()
        token = secrets.token_urlsafe(32)
        write_private(self.token_path, token.encode())
        return token


def write_private(path: Path, data: bytes) -> None:
    """Create a file readable only by the current user."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
