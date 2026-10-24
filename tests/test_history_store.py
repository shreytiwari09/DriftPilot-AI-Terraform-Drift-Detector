from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from driftpilot.collector import managed_resource_count, parse_plan, resource_values
from driftpilot.history.store import (
    GitHubBranchStore,
    LocalStore,
    append_scan,
    records_from_scan,
)
from driftpilot.models import RemediationResult, ScanResult
from driftpilot.triage.rules import apply_rules, load_rules

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def scan(plan: dict) -> ScanResult:
    findings = parse_plan(plan, "r1", NOW)
    return ScanResult(
        run_id="r1",
        started_at=NOW,
        working_dir="infra",
        findings=findings,
        verdicts=apply_rules(findings, load_rules(), resource_values(plan)),
        managed_resource_count=managed_resource_count(plan),
    )


def test_records_skip_noise_and_count_run(load_fixture) -> None:
    result = scan(load_fixture("github/batch_a_s2_s3_s5_s6_s7_s8"))
    pr = RemediationResult(
        finding_id="x", action="codify", verified=True, attempts=1, pr_url="u", finding_ids=[]
    )
    pr.finding_ids = [f.id for f in result.findings if f.attribute_path == "description"]
    result.remediations = [pr]
    events, run = records_from_scan(result)
    assert all(e.finding.attribute_path != "etag" for e in events)  # noise not stored
    assert (run.finding_count, run.critical_count, run.noise_count) == (6, 1, 2)
    assert run.distinct_resources == 3 and run.managed_resource_count == 5
    linked = [e for e in events if e.remediation]
    assert [e.finding.attribute_path for e in linked] == ["description"]
    untriaged = [e for e in events if e.verdict.source == "policy"]
    assert untriaged and untriaged[0].verdict.recommended_action == "investigate"


def test_clean_run_still_recorded(load_fixture) -> None:
    events, run = records_from_scan(scan(load_fixture("github/control_no_change")))
    assert events == [] and run.finding_count == 0


def test_local_store_round_trip(tmp_path: Path, load_fixture) -> None:
    store = LocalStore(tmp_path / "history")
    append_scan(store, scan(load_fixture("github/s2_required_approvals_reduced")))
    append_scan(store, scan(load_fixture("github/control_no_change")))
    assert len(store.load_runs()) == 2
    [event] = store.load_events()
    assert event.verdict.severity == "critical" and event.human_outcome == "pending"


def test_github_store_creates_branch_and_files() -> None:
    repo = MagicMock(default_branch="main")
    not_found = type("NotFound", (Exception,), {"status": 404})
    repo.get_branch.side_effect = [not_found(), SimpleNamespace(commit=SimpleNamespace(sha="s"))]
    repo.get_contents.side_effect = not_found()
    store = GitHubBranchStore(repo, "driftpilot-data")
    store.save([], [], "msg")
    repo.create_git_ref.assert_called_once_with(ref="refs/heads/driftpilot-data", sha="s")
    paths = [c.args[0] for c in repo.create_file.call_args_list]
    assert paths == ["history/drift-events.jsonl", "history/runs.jsonl"]
    assert repo.create_file.call_args.kwargs == {"branch": "driftpilot-data"}


def test_github_store_reads_existing() -> None:
    repo = MagicMock()
    line = (
        '{"run_id":"r","timestamp":"2026-10-25T00:00:00Z","working_dir":"infra","finding_count":0,'
        '"critical_count":0,"distinct_resources":0,"unmanaged_count":0,"noise_count":0}\n'
    )
    repo.get_contents.return_value = SimpleNamespace(decoded_content=line.encode(), sha="x")
    assert GitHubBranchStore(repo, "d").load_runs()[0].run_id == "r"
