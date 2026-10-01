"""Black-box harness: runs the real `groundzero` executable as a server and as a CLI client.

Nothing here imports application internals. Tests see only what a user or automation would see:
process exit codes, CLI output and HTTP responses.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

EXECUTABLE = str(Path(sys.executable).with_name("groundzero"))
REPO_ROOT = Path(__file__).resolve().parents[2]
R740XD_CAPTURE = REPO_ROOT / "tests" / "fixtures" / "dell-r740xd"
ESXI1_CAPTURE = REPO_ROOT / "tests" / "fixtures" / "esxi1-network.json"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class CliResult:
    code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


@dataclass
class GroundZero:
    """One isolated GroundZero installation: its own home dir, port and server process."""

    home: Path
    extra_env: dict[str, str] = field(default_factory=dict)
    port: int = field(default_factory=free_port)
    media_port: int = field(default_factory=free_port)
    _proc: subprocess.Popen[bytes] | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def media_url(self) -> str:
        return f"https://127.0.0.1:{self.media_port}"

    @property
    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GROUNDZERO_")}
        env.update(
            GROUNDZERO_HOME=str(self.home),
            GROUNDZERO_PORT=str(self.port),
            GROUNDZERO_MEDIA_PORT=str(self.media_port),
            GROUNDZERO_URL=self.url,
            COLUMNS="200",  # keep rich tables on one line so assertions are stable
            NO_COLOR="1",
        )
        env.update(self.extra_env)
        return env

    def start(self, timeout: float = 20.0) -> None:
        # Output goes to a file (an unread pipe can fill up and hang the server).
        # cwd=home so a developer's .env in the repo never leaks into the run.
        log = (self.home / "server.log").open("ab")
        self._proc = subprocess.Popen(
            [EXECUTABLE, "serve"], env=self.env, cwd=self.home, stdout=log, stderr=subprocess.STDOUT
        )
        log.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                out = (self.home / "server.log").read_text()
                raise RuntimeError(f"server exited early ({self._proc.returncode}):\n{out}")
            try:
                if httpx.get(self.url + "/healthz", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        self.stop()
        raise RuntimeError("server did not become healthy")

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def cli(self, *args: str, timeout: float = 120.0) -> CliResult:
        proc = subprocess.run(
            [EXECUTABLE, *args], env=self.env, cwd=self.home, capture_output=True, text=True, timeout=timeout
        )
        return CliResult(proc.returncode, proc.stdout, proc.stderr)

    def api(self) -> httpx.Client:
        token = self.cli("token", "show").stdout.strip()
        return httpx.Client(base_url=self.url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
