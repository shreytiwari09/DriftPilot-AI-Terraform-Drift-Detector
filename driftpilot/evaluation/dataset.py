"""Load the labelled evaluation cases in `eval/cases/*.yaml` (SPEC §8)."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from driftpilot.collector import finding_id
from driftpilot.models import Action, Severity, UnmanagedFinding
from driftpilot.scanners.docker import PROVIDER as DOCKER_PROVIDER
from driftpilot.scanners.github import PROVIDER as GITHUB_PROVIDER

PROVIDERS = {
    "github": GITHUB_PROVIDER,
    "docker": DOCKER_PROVIDER,
    "aws": "registry.terraform.io/hashicorp/aws",
}
EVAL_TIME = datetime(2026, 10, 25, tzinfo=UTC)  # fixed, so prompts (and the LLM cache) are stable


class Expected(BaseModel):
    address: str | None = None  # needed when the input has several resources
    attribute: str | None = None  # None = whole resource (deleted) or unmanaged
    real: bool
    severity: Severity
    action: list[Action]


class InlineDrift(BaseModel):
    address: str
    before: Any = None
    after: Any = None
    actions: list[str] = ["update"]


class UnmanagedSpec(BaseModel):
    provider: Literal["github", "docker"]
    kind: str
    name: str


class Case(BaseModel):
    id: str
    source: Literal["recorded", "synthetic"]
    scenario: int | list[int] | None = None
    fixture: str | None = None
    drift: list[InlineDrift] | None = None
    unmanaged: UnmanagedSpec | None = None
    code_dir: str | None = None
    code: str | None = None
    default: Literal["noise"] | None = None
    expect: list[Expected] = Field(default_factory=list)
    file: str = ""

    def plan(self, fixtures: Path) -> dict | None:
        if self.fixture:
            return json.loads((fixtures / f"{self.fixture}.json").read_text())
        if self.drift:
            return {"resource_drift": [_drift_entry(d) for d in self.drift]}
        return None

    def unmanaged_finding(self) -> UnmanagedFinding | None:
        if self.unmanaged is None:
            return None
        u = self.unmanaged
        provider = PROVIDERS[u.provider]
        resource_id = f"{u.kind}-{u.name}"
        return UnmanagedFinding(
            id=finding_id(f"{provider}:{u.kind}", resource_id),
            run_id=self.id,
            detected_at=EVAL_TIME,
            provider=provider,
            resource_kind=u.kind,
            resource_id=resource_id,
            name=u.name,
        )

    def code_path(self, root: Path) -> Path | None:
        """Directory holding the resource's code: a repo folder, or a temp dir for inline code."""
        if self.code_dir:
            return root / self.code_dir
        if self.code:
            tmp = Path(tempfile.mkdtemp(prefix=f"driftpilot-eval-{self.id}-"))
            (tmp / "main.tf").write_text(self.code)
            return tmp
        return None


def _drift_entry(d: InlineDrift) -> dict:
    rtype = d.address.split(".")[0]
    provider = next((p for prefix, p in PROVIDERS.items() if rtype.startswith(f"{prefix}_")), "")
    return {
        "address": d.address,
        "type": rtype,
        "provider_name": provider,
        "change": {"actions": d.actions, "before": d.before, "after": d.after},
    }


def load_cases(directory: Path) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(directory.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text()) or []:
            cases.append(Case.model_validate({**raw, "file": path.name}))
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
    for c in cases:
        inputs = [c.fixture is not None, c.drift is not None, c.unmanaged is not None]
        if sum(inputs) != 1:
            raise ValueError(f"case {c.id}: give exactly one of fixture, drift, unmanaged")
    return cases
