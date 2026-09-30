"""Service metadata: health and available preflight profiles."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from groundzero import __version__
from groundzero.preflight.evaluate import Variant, available_profiles, load_profile

health_router = APIRouter(tags=["meta"])
router = APIRouter(tags=["meta"])


class Health(BaseModel):
    status: str
    version: str


class ProfileSummary(BaseModel):
    id: str
    title: str
    source: str
    default_variant: str
    variants: list[Variant]


@health_router.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(status="ok", version=__version__)


@router.get("/profiles", response_model=list[ProfileSummary])
def list_profiles() -> list[ProfileSummary]:
    summaries = []
    for profile_id in available_profiles():
        p = load_profile(profile_id)
        summaries.append(
            ProfileSummary(
                id=p.id,
                title=p.title,
                source=p.source,
                default_variant=p.default_variant,
                variants=list(p.variants.values()),
            )
        )
    return summaries
