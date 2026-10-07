"""Per-job diagnostics: a redacted record of what a job saw and did, for debugging from a log.

Redfish is a standard, but every vendor implements it differently. When a job fails on hardware we
have not seen, the bundle (``GET /jobs/{id}/diagnostics``) should be enough to understand why:
every BMC exchange (method, path, status, timing, truncated body), the BMC's identity, the job's steps,
ESXi/SSH operations and the error with its traceback.

The recorder is job-scoped through a context variable, so the Redfish client and ESXi reader record into
the current job without any plumbing. Secrets never reach the bundle: values under sensitive keys are
replaced, known secret strings (passwords handed to clients) are scrubbed everywhere, and media URL
tokens are masked.
"""

from __future__ import annotations

import json
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

MAX_EVENTS = 4000
MAX_BODY_CHARS = 16_000
REDACTED = "«redacted»"

# Whole key names (or their last _-./ separated part): "Password", "root_password", "X-Auth-Token"; and any
# key ending in password or secret, as BIOS attributes are named ("SetupPassword", "...ChapSecret").
_SENSITIVE_KEY = re.compile(
    r"(?:password|passwd|passphrase|secret)$"
    r"|(?:^|[_\-.])(?:pass|token|authorization|cookie|api[-_]?key|private[-_]?key|credentials?)$",
    re.IGNORECASE,
)
_MEDIA_TOKEN = re.compile(r"(/media/)[^/\s\"']+(/)")

current: ContextVar[Diagnostics | None] = ContextVar("groundzero_diagnostics", default=None)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def redact(value: Any) -> Any:
    """Replace values under sensitive keys (recursively); mask media URL tokens in strings."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if _SENSITIVE_KEY.search(str(k)) and _has_value(v) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _MEDIA_TOKEN.sub(r"\1«token»\2", value)
    return value


def _has_value(v: Any) -> bool:
    return v not in (None, "") and not isinstance(v, bool)


def truncate(value: Any, limit: int = MAX_BODY_CHARS) -> Any:
    """Keep small bodies as structured JSON; cut large ones to a string with a marker."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    return text[:limit] + f"… [truncated, {len(text)} chars]"


class Diagnostics:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.events: list[dict[str, Any]] = []
        self.dropped = 0
        self._secrets: set[str] = set()

    def add_secret(self, *values: str | None) -> None:
        """Strings that must never appear in the bundle (scrubbed at export)."""
        self._secrets.update(v for v in values if v and len(v) >= 4)

    def record(self, event: str, /, **data: Any) -> None:
        if len(self.events) >= MAX_EVENTS:
            self.dropped += 1
            return
        self.events.append({"at": _now(), "event": event, **redact(data)})

    def export(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"events": self.events, "dropped_events": self.dropped}
        text = json.dumps(payload, default=str)
        for secret in sorted(self._secrets, key=len, reverse=True):
            text = text.replace(json.dumps(secret)[1:-1], REDACTED)
        exported: dict[str, Any] = json.loads(text)
        return exported


def record(event: str, /, **data: Any) -> None:
    """Record into the current job's diagnostics, if any (no-op outside a job)."""
    diag = current.get()
    if diag is not None:
        diag.record(event, **data)


def add_secret(*values: str | None) -> None:
    diag = current.get()
    if diag is not None:
        diag.add_secret(*values)
