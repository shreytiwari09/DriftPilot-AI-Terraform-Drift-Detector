"""One drift scan: plan → findings → rules → scanners → LLM triage → policy."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from driftpilot.collector import (
    managed_resource_count,
    parse_plan,
    refresh_only_plan,
    resource_values,
    show_state,
    terraform_init,
)
from driftpilot.config import Config
from driftpilot.models import ScanResult, UnmanagedFinding
from driftpilot.scanners import build_scanners
from driftpilot.scanners.base import find_unmanaged
from driftpilot.triage.llm import LLMClient
from driftpilot.triage.llm_triage import triage_findings
from driftpilot.triage.policy import apply_policy
from driftpilot.triage.rules import apply_rules, load_rules


def _scan_unmanaged(
    result: ScanResult,
    config: Config,
    working_dir: Path,
    replaying: bool,
    state_json: Path | None,
) -> list[UnmanagedFinding]:
    # Scanners need state; in replay mode they only run if a recorded state is given.
    if replaying and state_json is None:
        return []
    try:
        scanners = build_scanners(config)
    except Exception as e:  # e.g. missing token: report it, keep the drift results
        result.errors.append(f"scanners: {e}")
        return []
    if not scanners:
        return []
    state = json.loads(state_json.read_text()) if state_json else show_state(working_dir)
    unmanaged: list[UnmanagedFinding] = []
    for scanner in scanners:
        try:
            unmanaged += find_unmanaged(scanner, state, result.run_id, result.started_at)
        except Exception as e:  # one platform failing shouldn't hide the others
            result.errors.append(f"{type(scanner).__name__}: {e}")
    return unmanaged


def run_scan(
    working_dir: Path,
    config: Config,
    plan_json: Path | None = None,
    state_json: Path | None = None,
    llm: LLMClient | None = None,
) -> ScanResult:
    """Run a scan. `plan_json` / `state_json` replay recorded files instead of calling Terraform.

    Without an `llm`, findings no rule decides stay undecided ("needs triage").
    """
    now = datetime.now(UTC)
    result = ScanResult(
        run_id=f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}",
        started_at=now,
        working_dir=str(working_dir),
    )

    if plan_json is None:
        terraform_init(working_dir)
        plan = refresh_only_plan(working_dir)
    else:
        plan = json.loads(plan_json.read_text())
    result.findings = parse_plan(plan, result.run_id, now)
    result.managed_resource_count = managed_resource_count(plan)
    result.verdicts = apply_rules(result.findings, load_rules(), resource_values(plan))
    result.unmanaged = _scan_unmanaged(
        result, config, working_dir, plan_json is not None, state_json
    )

    if llm is not None:
        result.verdicts |= triage_findings(llm, result.findings, result.verdicts, working_dir)
    result.verdicts = apply_policy(result.findings, result.unmanaged, result.verdicts, config)
    return result
