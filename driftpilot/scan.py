"""One drift scan: plan → findings → rules → scanners → LLM triage → policy."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from driftpilot.cloud_events import CloudEvent, attach_event_context
from driftpilot.collector import (
    managed_resource_count,
    managed_resources,
    parse_plan,
    refresh_only_plan,
    resource_values,
    show_state,
    terraform_init,
)
from driftpilot.config import Config
from driftpilot.database.diff import diff_catalogs, table_address
from driftpilot.database.scan import Catalogs, load_catalogs
from driftpilot.models import GuardrailEvent, ScanResult, UnmanagedFinding
from driftpilot.ownership import apply_ownership
from driftpilot.scanners import build_scanners
from driftpilot.scanners.base import find_unmanaged
from driftpilot.triage.llm import AuditingLLM, LLMClient
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


def attach_audit(result: ScanResult, llm: LLMClient | None, since: int = 0) -> None:
    """Copy the LLM audit trail and budget state onto the result (safe to call again later).

    `since`: skip the first calls, which belong to an earlier scan in the same process.
    """
    if not isinstance(llm, AuditingLLM):
        return
    result.audit = llm.collect(result.run_id, since)
    result.llm_call_limit = llm.call_limit
    result.guardrail_events = [e for e in result.guardrail_events if e.kind != "budget-exceeded"]
    if llm.budget_exceeded:
        result.guardrail_events.append(
            GuardrailEvent(kind="budget-exceeded", detail=llm.budget_exceeded)
        )


def run_scan(
    working_dir: Path,
    config: Config,
    plan_json: Path | None = None,
    state_json: Path | None = None,
    llm: LLMClient | None = None,
    events: list[CloudEvent] | None = None,
) -> ScanResult:
    """Run a scan. `plan_json` / `state_json` replay recorded files instead of calling Terraform.

    Without an `llm`, findings no rule decides stay undecided ("needs triage"). `events` are cloud
    audit events: the one that touched a resource is attached ("changed by ...") before triage.
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
    resources = resource_values(plan)
    result.verdicts = apply_rules(result.findings, load_rules(), resources)
    result.unmanaged = _scan_unmanaged(
        result, config, working_dir, plan_json is not None, state_json
    )

    attach_event_context(result.findings, result.unmanaged, resources, events or [])

    if llm is not None:
        result.verdicts |= triage_findings(
            llm,
            result.findings,
            result.verdicts,
            working_dir,
            guardrails=config.guardrails.enabled,
            events=result.guardrail_events,
        )
    result.verdicts = apply_policy(
        result.findings,
        result.unmanaged,
        result.verdicts,
        config,
        resources,
        result.guardrail_events,
    )
    apply_ownership(result, config, working_dir, resources, managed_resources(plan))
    attach_audit(result, llm)
    return result


def run_database_scan(
    working_dir: Path,
    config: Config,
    llm: LLMClient | None = None,
    expected_json: Path | None = None,
    live_json: Path | None = None,
    catalogs: Catalogs | None = None,
    audit_since: int = 0,
) -> ScanResult:
    """Compare the schema the migrations build with the live Postgres schema.

    Same pipeline as `run_scan`: rules, LLM triage, guardrails, policy, ownership. `expected_json` /
    `live_json` replay saved catalogs instead of using the databases; `catalogs` reuses ones read
    already.
    """
    now = datetime.now(UTC)
    result = ScanResult(
        run_id=f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}",
        started_at=now,
        working_dir=str(working_dir),
    )
    catalogs = catalogs or load_catalogs(working_dir, config, expected_json, live_json)
    ignore = config.database.ignore
    expected, live = catalogs.expected.filtered(ignore), catalogs.live.filtered(ignore)
    result.findings = diff_catalogs(expected, live, result.run_id, now)
    result.managed_resource_count = len(expected.tables)
    result.verdicts = apply_rules(result.findings, load_rules(), {})
    if llm is not None:
        result.verdicts |= triage_findings(
            llm,
            result.findings,
            result.verdicts,
            None,
            guardrails=config.guardrails.enabled,
            events=result.guardrail_events,
        )
    result.verdicts = apply_policy(
        result.findings, [], result.verdicts, config, {}, result.guardrail_events
    )
    managed = [{"address": table_address(t), "values": None} for t in expected.tables]
    apply_ownership(result, config, working_dir, {}, managed, drift_type="database")
    attach_audit(result, llm, audit_since)
    return result
