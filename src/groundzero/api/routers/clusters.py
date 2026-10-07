"""/api/v1/clusters: servers named after their BMC, addressed from a pool, optionally checked in DNS."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from groundzero.api.deps import ServicesDep
from groundzero.clusters import Cluster, ClusterMember, ClusterWrite

router = APIRouter(prefix="/clusters", tags=["clusters"])


class MemberAdd(BaseModel):
    host_id: str


@router.get("", response_model=list[Cluster])
def list_clusters(services: ServicesDep) -> list[Cluster]:
    return services.list_clusters()


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Cluster)
def create_cluster(body: ClusterWrite, services: ServicesDep, response: Response) -> Cluster:
    cluster = services.save_cluster(body)
    response.headers["Location"] = f"/api/v1/clusters/{cluster.id}"
    return cluster


@router.get("/{cluster_id}", response_model=Cluster)
def get_cluster(cluster_id: str, services: ServicesDep) -> Cluster:
    return services.get_cluster(cluster_id)


@router.put("/{cluster_id}", response_model=Cluster)
def update_cluster(cluster_id: str, body: ClusterWrite, services: ServicesDep) -> Cluster:
    """Change the cluster. Members keep their names and addresses; the range must still contain them."""
    return services.save_cluster(body, cluster_id)


@router.delete("/{cluster_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cluster(cluster_id: str, services: ServicesDep) -> None:
    """Members keep their hostnames and IPs as their own per-host values."""
    services.delete_cluster(cluster_id)


@router.post("/{cluster_id}/members", status_code=status.HTTP_201_CREATED, response_model=ClusterMember)
async def add_member(cluster_id: str, body: MemberAdd, services: ServicesDep) -> ClusterMember:
    """Add a server: its hostname comes from its BMC's name (read-only), its IP is the next free one in the
    range, and both are written as its per-host values."""
    return await services.add_cluster_member(cluster_id, body.host_id)


@router.delete("/{cluster_id}/members/{host_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(cluster_id: str, host_id: str, services: ServicesDep) -> None:
    services.remove_cluster_member(cluster_id, host_id)
