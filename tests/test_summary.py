from datetime import UTC, datetime

from driftpilot.collector import parse_plan, resource_values
from driftpilot.models import ScanResult, UnmanagedFinding
from driftpilot.report.summary import build_summary
from driftpilot.triage.rules import apply_rules, load_rules

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def result_from(plan: dict) -> ScanResult:
    findings = parse_plan(plan, "r1", NOW)
    return ScanResult(
        run_id="r1",
        started_at=NOW,
        working_dir="infra/",
        findings=findings,
        verdicts=apply_rules(findings, load_rules(), resource_values(plan)),
    )


def test_no_drift_message(load_fixture) -> None:
    md = build_summary(result_from(load_fixture("github/control_no_change")))
    assert "No drift detected" in md


def test_noise_only_counts_as_no_drift(load_fixture) -> None:
    md = build_summary(result_from(load_fixture("github/noise_provider_defaults_after_apply")))
    assert "No drift detected" in md
    assert "noise finding(s) filtered" in md


def test_critical_row_and_counts(load_fixture) -> None:
    md = build_summary(result_from(load_fixture("github/s2_required_approvals_reduced")))
    assert "| 1 | 0 | 0 | 0 | 0 | 0 |" in md
    assert "🔴 critical" in md
    assert "github-required-approvals-reduced" in md


def test_needs_triage_and_unmanaged(load_fixture) -> None:
    result = result_from(load_fixture("docker/s11_memory_changed"))
    result.unmanaged.append(
        UnmanagedFinding(
            id="u1",
            run_id="r1",
            detected_at=NOW,
            provider="p",
            resource_kind="repository",
            resource_id="1000",
            name="demo|handmade",
        )
    )
    md = build_summary(result)
    assert "⚪ needs triage" in md
    assert "### Unmanaged resources" in md
    assert "`demo\\|handmade`" in md  # pipes escaped so the table doesn't break


def test_no_guardrails_section_without_llm_activity(load_fixture) -> None:
    md = build_summary(result_from(load_fixture("github/s2_required_approvals_reduced")))
    assert "Guardrails" not in md


def test_guardrails_section_lists_calls_overrides_and_suspicious_inputs(load_fixture) -> None:
    from driftpilot.models import AuditRecord, GuardrailEvent

    result = result_from(load_fixture("github/s2_required_approvals_reduced"))
    record = AuditRecord(timestamp=NOW, purpose="triage", model="m", prompt_sha256="a" * 64)
    result.audit = [record, record]
    result.llm_call_limit = 60
    result.guardrail_events = [
        GuardrailEvent(kind="never-soften", finding_id="f1", detail="encryption off"),
        GuardrailEvent(kind="suspicious-input", finding_id="f2", detail="ignore-instructions"),
        GuardrailEvent(kind="budget-exceeded", detail="60 LLM calls per run"),
        GuardrailEvent(kind="pr-limit", detail="codify:x: more than 5 PR(s) in one run"),
    ]
    md = build_summary(result)
    assert "### Guardrails" in md
    assert "LLM calls: 2 of 60" in md
    assert "Never-soften overrides: 1" in md and "encryption off" in md
    assert "Suspicious inputs: 1" in md and "ignore-instructions" in md
    assert "budget exceeded" in md.lower() and "PR(s)" in md


def test_guardrails_section_shows_when_only_calls_were_made(load_fixture) -> None:
    from driftpilot.models import AuditRecord

    result = result_from(load_fixture("github/s2_required_approvals_reduced"))
    result.audit = [AuditRecord(timestamp=NOW, purpose="triage", model="m", prompt_sha256="a" * 64)]
    md = build_summary(result)
    assert "LLM calls: 1" in md and "Never-soften overrides: 0" in md
