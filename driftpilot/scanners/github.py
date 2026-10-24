"""GitHub scanner: org repos and teams that aren't in state."""

from typing import Any

from driftpilot.models import ScannedResource
from driftpilot.scanners.base import state_resources

PROVIDER = "registry.terraform.io/integrations/github"


class GitHubScanner:
    provider = PROVIDER

    def __init__(self, client: Any, owner: str, ignore_names: list[str]) -> None:
        self.client = client  # github.Github; injected so tests can pass a mock
        self.owner = owner
        self.ignore_names = ignore_names

    def list_resources(self) -> list[ScannedResource]:
        org = self.client.get_organization(self.owner)
        resources = [
            ScannedResource(
                provider=PROVIDER,
                resource_kind="repository",
                resource_id=str(r.id),
                name=r.name,
                created_at=r.created_at,
            )
            for r in org.get_repos(type="all")
        ]
        resources += [
            ScannedResource(
                provider=PROVIDER, resource_kind="team", resource_id=str(t.id), name=t.slug
            )
            for t in org.get_teams()
        ]
        return resources

    def managed_ids(self, state: dict[str, Any]) -> set[str]:
        # Compare on numeric IDs, not names: a renamed repo keeps its ID.
        ids: set[str] = set()
        for r in state_resources(state):
            if r.get("mode") != "managed":
                continue
            if r.get("type") == "github_repository":
                ids.add(str(r["values"]["repo_id"]))
            elif r.get("type") == "github_team":
                ids.add(str(r["values"]["id"]))
        return ids
