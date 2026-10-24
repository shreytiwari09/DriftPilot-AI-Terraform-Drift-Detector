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
