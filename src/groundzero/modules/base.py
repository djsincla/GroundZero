"""The module contract: one class per pipeline task.

A module declares what it is (id, title, stage), what it needs (output kinds of earlier modules, or OS
access), what it produces (an output kind) and its parameters (a Pydantic model, so its JSON Schema drives
the web form and ``groundzero run --param``). ``prepare`` validates everything that can be checked before
a job is queued (a bad input is a 4xx, not a failed job) and returns the job body.

Outputs flow between modules through the store: a module reads its inputs with ``Inputs`` (typed, validated
against the output registry) and saves what it produces with ``deps.save_output``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from groundzero.core.jobs import JobContext
from groundzero.core.models import Host, OsAccess
from groundzero.core.store import OutputMeta, Store
from groundzero.core.tasks import OS_ACCESS, Stage, TaskSpec

if TYPE_CHECKING:
    from groundzero.clusters import Cluster
    from groundzero.core.config import Settings
    from groundzero.core.models import ConfigSet, ConfigSetWrite
    from groundzero.dnscheck import DnsLookup
    from groundzero.esxi.models import EsxiNetworkConfig, EsxiStorage
    from groundzero.esxi.ops import EsxiOps
    from groundzero.inventory.models import HostInventory
    from groundzero.isos import IsoRepository
    from groundzero.media.registry import MediaRegistry
    from groundzero.ova.profiles import ApplianceProfile, ApplianceProfileWrite
    from groundzero.readiness import ReadinessReport
    from groundzero.redfish.client import RedfishClient

__all__ = ["OS_ACCESS", "Deps", "Inputs", "Module", "NoParams", "Prepared", "Stage"]

M = TypeVar("M", bound=BaseModel)
RunFunc = Callable[[JobContext], Awaitable[dict[str, Any]]]


class NoParams(BaseModel):
    """For modules that take no parameters (unknown keys are ignored, as the old endpoints did)."""

    model_config = ConfigDict(extra="ignore")


@dataclass
class Prepared:
    """A validated run: the job body and the parameters recorded on the job."""

    run: RunFunc
    params: dict[str, Any] = field(default_factory=dict)


class Deps(Protocol):
    """What modules may use from the application (implemented by ``Services``)."""

    settings: Settings
    store: Store
    esxi: EsxiOps
    isos: IsoRepository

    media: MediaRegistry
    dns: DnsLookup

    def client_factory(self, host: Host, password: str) -> RedfishClient: ...
    def bmc_password(self, host_id: str) -> str: ...
    def os_access(self, host_id: str) -> tuple[OsAccess, str]: ...
    def stored_os_access(self, host_id: str) -> tuple[OsAccess, str] | None: ...
    def save_os_access(self, host_id: str, access: OsAccess, password: str) -> None: ...
    def validate_values(self, model: type[BaseModel], data: dict[str, Any], where: str) -> dict[str, Any]: ...
    async def wait_for_port(self, address: str, port: int, *, minutes: float, ctx: JobContext) -> None: ...
    def os_target(self, host_id: str, access: OsAccess, *, repin: bool = False) -> OsAccess: ...
    async def collect_inventory(
        self, host: Host, ctx: JobContext
    ) -> tuple[HostInventory, dict[str, Any]]: ...
    def save_output(
        self, host_id: str, kind: str, job_id: str, output: BaseModel | dict[str, Any], *, source: str = "job"
    ) -> None: ...
    def reassess(
        self, host_id: str, network: EsxiNetworkConfig, storage: EsxiStorage, job_id: str
    ) -> ReadinessReport: ...
    def create_config_set(self, req: ConfigSetWrite, source: str = "manual") -> ConfigSet: ...
    def get_config_set(self, set_id: str) -> ConfigSet: ...
    def get_appliance_profile(self, profile_id: str) -> ApplianceProfile: ...
    def cluster_for_host(self, host_id: str) -> Cluster | None: ...
    def appliance_profile_secrets(self, profile_id: str) -> dict[str, str]: ...
    def save_appliance_profile(
        self, req: ApplianceProfileWrite, *, profile_id: str | None = None, source: str = "manual"
    ) -> ApplianceProfile: ...
    def config_set_secrets(self, set_id: str) -> dict[str, str]: ...


class Inputs:
    """The outputs of earlier modules, as this module sees them: typed, and current for the installed OS."""

    def __init__(self, store: Store, host_id: str) -> None:
        self._store = store
        self._host_id = host_id
        self._epoch = store.os_epoch(host_id)

    def meta(self, kind: str) -> OutputMeta | None:
        return self._store.latest_output(host_id=self._host_id, kind=kind)

    def get(self, kind: str, model: type[M], *, current: bool = False) -> M | None:
        """The latest ``kind`` output, or None. ``current``: only if produced on the installed OS."""
        meta = self.meta(kind)
        if meta is None or (current and meta.epoch < self._epoch):
            return None
        try:
            return model.model_validate(meta.data)
        except ValidationError as exc:
            from groundzero.core.services import ConflictError

            raise ConflictError(
                f"The stored {kind} output is unreadable; run its task again ({exc})"
            ) from exc

    def require(self, kind: str, model: type[M], missing: str) -> M:
        value = self.get(kind, model)
        if value is None:
            from groundzero.core.services import ConflictError

            raise ConflictError(missing)
        return value


class Module:
    """Base class: subclasses set the class attributes and implement ``prepare``."""

    id: ClassVar[str]
    title: ClassVar[str]
    stage: ClassVar[Stage]
    description: ClassVar[str]
    produces: ClassVar[str | None] = None
    requires: ClassVar[tuple[str, ...]] = ()  # output kinds, or OS_ACCESS
    os_bound: ClassVar[bool] = False  # the output describes the installed OS: stale after a reinstall
    optional: ClassVar[bool] = False  # not on the recommended path (alternatives, utilities)
    conditional: ClassVar[bool] = False  # optional, but recommended once ready (see ``satisfied``)
    destructive: ClassVar[bool] = False
    available: ClassVar[bool] = True  # False: designed, not implemented yet (shown as planned)
    uses: ClassVar[tuple[str, ...]] = ()  # optional inputs: read when present, never blocking
    also_produces: ClassVar[tuple[str, ...]] = ()  # side outputs
    Params: ClassVar[type[BaseModel]] = NoParams

    @classmethod
    def spec(cls) -> TaskSpec:
        return TaskSpec(
            cls.id,
            cls.title,
            cls.stage,
            cls.description,
            produces=cls.produces,
            requires=cls.requires,
            os_bound=cls.os_bound,
            optional=cls.optional,
            conditional=cls.conditional,
            destructive=cls.destructive,
            available=cls.available,
            uses=cls.uses,
            also_produces=cls.also_produces,
        )

    @classmethod
    def params_schema(cls) -> dict[str, Any]:
        return cls.Params.model_json_schema()

    def summarize(self, data: dict[str, Any]) -> str:
        """One line describing this module's output, for the pipeline view."""
        return self.produces or self.id

    def satisfied(self, outputs: dict[str, dict[str, Any]]) -> str | None:
        """Why there is nothing to do, judged from this host's current outputs; None when there may be.

        A ready task that is satisfied is shown as "not needed" instead of waiting to be run.
        """
        return None

    def prepare(
        self, deps: Deps, host: Host, params: Any, inputs: Inputs, confirm: str | None
    ) -> Prepared:  # pragma: no cover - planned modules are never prepared
        raise NotImplementedError(f"{self.title} is not available yet")
