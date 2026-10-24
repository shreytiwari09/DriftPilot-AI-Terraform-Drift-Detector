"""All DriftPilot data models (SPEC §3)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "high", "medium", "low", "none"]
Category = Literal["security", "cost", "availability", "cosmetic"]
Intent = Literal["likely_hotfix", "likely_accidental", "likely_automation", "unknown"]
Action = Literal["revert", "codify", "ignore_changes", "import", "recreate", "investigate", "none"]


class DriftFinding(BaseModel):
    """One changed attribute (or one deleted resource) found by a refresh-only plan."""

    id: str  # stable hash of (address, attribute_path)
    run_id: str
    detected_at: datetime
    provider: str
    resource_type: str
    address: str
    change_kind: Literal["modified", "deleted"]
    attribute_path: str | None
    before: Any  # redacted
    after: Any  # redacted
    sensitive: bool = False


class ScannedResource(BaseModel):
    """A resource as a platform API lists it, before comparing with Terraform state."""

    provider: str
    resource_kind: str
    resource_id: str
    name: str
    created_at: datetime | None = None


class UnmanagedFinding(BaseModel):
    """A resource that exists on the platform but not in Terraform state."""

    id: str
    run_id: str
    detected_at: datetime
    provider: str
    resource_kind: str
    resource_id: str
    name: str
    created_at: datetime | None = None


class Verdict(BaseModel):
    finding_id: str
    source: Literal["rule", "llm", "policy"]
    is_real_drift: bool
    severity: Severity
    category: Category
    intent: Intent
    recommended_action: Action
    confidence: float = Field(ge=0, le=1)
    reason: str
    prompt_version: str | None = None
    rule_id: str | None = None


class RemediationResult(BaseModel):
    finding_id: str
    action: str
    verified: bool
    attempts: int
    pr_url: str | None = None
    issue_url: str | None = None
    plan_proof: str | None = None


class HistoryEvent(BaseModel):
    """One line in drift-events.jsonl."""

    run_id: str
    timestamp: datetime
    finding: DriftFinding | UnmanagedFinding
    verdict: Verdict
    remediation: RemediationResult | None = None
    human_outcome: Literal["accepted", "overruled", "pending"] = "pending"


class ScanResult(BaseModel):
    """Everything one `driftpilot scan` produced."""

    run_id: str
    started_at: datetime
    working_dir: str
    findings: list[DriftFinding] = []
    unmanaged: list[UnmanagedFinding] = []
    verdicts: dict[str, Verdict] = {}  # keyed by finding id; missing = needs triage
    remediations: list[RemediationResult] = []
    errors: list[str] = []

    def verdict_for(self, finding_id: str) -> Verdict | None:
        return self.verdicts.get(finding_id)

    @property
    def real_findings(self) -> list[DriftFinding]:
        """Findings not ruled out as noise (undecided ones count as real until triaged)."""
        return [
            f for f in self.findings if (v := self.verdicts.get(f.id)) is None or v.is_real_drift
        ]
