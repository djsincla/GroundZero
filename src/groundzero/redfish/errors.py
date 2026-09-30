"""Typed Redfish failures. Callers never have to interpret ``None`` as "something went wrong"."""

from __future__ import annotations


class RedfishError(Exception):
    error_type = "redfish_error"

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        path: str | None = None,
        message_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.status = status
        self.path = path
        self.message_ids = message_ids


class RedfishTransportError(RedfishError):
    """Network, TLS or timeout failure: the BMC could not be reached."""

    error_type = "redfish_transport"


class RedfishAuthError(RedfishError):
    error_type = "redfish_auth"


class RedfishNotFoundError(RedfishError):
    error_type = "redfish_not_found"


class RedfishUnsupportedError(RedfishError):
    """The BMC does not implement the requested operation (405/501)."""

    error_type = "redfish_unsupported"


class RedfishServerError(RedfishError):
    error_type = "redfish_server"
