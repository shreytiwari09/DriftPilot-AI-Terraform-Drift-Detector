"""Scanner interface: find platform resources that Terraform state doesn't know about.

See SPEC §4.3.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from typing import Any, Protocol

from driftpilot.collector import finding_id
from driftpilot.models import ScannedResource, UnmanagedFinding


@dataclass(frozen=True)
class ImportTarget:
    """How to bring an unmanaged resource into Terraform."""

    tf_type: str  # e.g. "github_repository"
    import_id: str  # what `terraform import` expects for this type
    name: str  # Terraform resource name, e.g. "demo_handmade"

    @property
    def address(self) -> str:
        return f"{self.tf_type}.{self.name}"


def tf_name(name: str) -> str:
    """A valid Terraform resource name from a platform name: `demo-handmade` → `demo_handmade`."""
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_").lower() or "resource"
    return f"r_{cleaned}" if cleaned[0].isdigit() else cleaned


class Scanner(Protocol):
    provider: str
    ignore_names: list[str]

    def list_resources(self) -> list[ScannedResource]: ...

    def managed_ids(self, state: dict[str, Any]) -> set[str]: ...


def state_resources(state: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every resource in `terraform show -json` state output, including those in child modules."""
    modules = [state.get("values", {}).get("root_module", {})]
    while modules:
        module = modules.pop()
        yield from module.get("resources", [])
        modules.extend(module.get("child_modules", []))


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse API timestamps, tolerating nanoseconds (Docker) and a trailing Z."""
    if not value:
        return None
    value = re.sub(r"(\.\d{6})\d+", r"\1", value.replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def find_unmanaged(
    scanner: Scanner, state: dict[str, Any], run_id: str, detected_at: datetime
) -> list[UnmanagedFinding]:
    managed = scanner.managed_ids(state)
    return [
        UnmanagedFinding(
            id=finding_id(f"{r.provider}:{r.resource_kind}", r.resource_id),
            run_id=run_id,
            detected_at=detected_at,
            **r.model_dump(),
        )
        for r in scanner.list_resources()
        if r.resource_id not in managed
        and not any(fnmatch(r.name, pattern) for pattern in scanner.ignore_names)
    ]
