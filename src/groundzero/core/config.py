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
    api_token: str | None = None
    bmc_username: str | None = None
    bmc_password: SecretStr | None = None
    # Simulation mode: serve every BMC from a recorded capture directory instead of the network.
    # Used for demos and black-box functional tests; reported by /healthz as mode "simulated".
    simulate_bmc_dir: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.home / "groundzero.sqlite3"

    @property
    def token_path(self) -> Path:
        return self.home / "api-token"

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
