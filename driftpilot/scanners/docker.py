"""Docker scanner: labelled containers, networks and volumes that aren't in state."""

from typing import Any

from driftpilot.models import ScannedResource, UnmanagedFinding
from driftpilot.scanners.base import ImportTarget, parse_timestamp, state_resources, tf_name

PROVIDER = "registry.terraform.io/kreuzwerker/docker"
_MANAGED_TYPES = {"docker_container", "docker_network", "docker_volume"}
_TF_TYPES = {
    "container": "docker_container",
    "network": "docker_network",
    "volume": "docker_volume",
}


def import_target(u: UnmanagedFinding) -> ImportTarget | None:
    tf_type = _TF_TYPES.get(u.resource_kind)
    return ImportTarget(tf_type, u.resource_id, tf_name(u.name)) if tf_type else None


class DockerScanner:
    provider = PROVIDER

    def __init__(self, client: Any, managed_label: str, ignore_names: list[str]) -> None:
        self.client = client  # docker.DockerClient; injected so tests can pass a mock
        self.label = managed_label
        self.ignore_names = ignore_names

    def list_resources(self) -> list[ScannedResource]:
        filters = {"label": self.label}
        resources = [
            ScannedResource(
                provider=PROVIDER,
                resource_kind="container",
                resource_id=c.id,
                name=c.name,
                created_at=parse_timestamp(c.attrs.get("Created")),
            )
            for c in self.client.containers.list(all=True, filters=filters)
        ]
        resources += [
            ScannedResource(
                provider=PROVIDER,
                resource_kind="network",
                resource_id=n.id,
                name=n.name,
                created_at=parse_timestamp(n.attrs.get("Created")),
            )
            for n in self.client.networks.list(filters=filters)
        ]
        resources += [
            ScannedResource(
                provider=PROVIDER,
                resource_kind="volume",
                resource_id=v.name,  # volumes are identified by name, as in Terraform state
                name=v.name,
                created_at=parse_timestamp(v.attrs.get("CreatedAt")),
            )
            for v in self.client.volumes.list(filters=filters)
        ]
        return resources

    def managed_ids(self, state: dict[str, Any]) -> set[str]:
        return {
            r["values"]["id"]
            for r in state_resources(state)
            if r.get("type") in _MANAGED_TYPES and r.get("mode") == "managed"
        }
