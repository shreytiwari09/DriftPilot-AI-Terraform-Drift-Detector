import json
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
FIXTURES_DIR = Path(__file__).parent / "fixtures"


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


def audit_record(run_id="r1", purpose="triage"):
    from driftpilot.models import AuditRecord

    return AuditRecord(
        run_id=run_id, timestamp=NOW, purpose=purpose, model="m", prompt_sha256="a" * 64, valid=True
    )


def test_local_store_appends_audit_lines(tmp_path: Path) -> None:
    store = LocalStore(tmp_path / "history")
    store.append_audit([audit_record("r1")], "m")
    store.append_audit([audit_record("r2", "codify"), audit_record("r2", "import")], "m")
    store.append_audit([], "m")  # nothing to write
    lines = (tmp_path / "history" / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 3
    assert [r.run_id for r in store.load_audit()] == ["r1", "r2", "r2"]


def test_old_stores_without_audit_load_empty(tmp_path: Path) -> None:
    assert LocalStore(tmp_path).load_audit() == []


def test_append_scan_writes_audit_next_to_events(tmp_path: Path, load_fixture) -> None:
    result = scan(load_fixture("github/s2_required_approvals_reduced"))
    result.audit = [audit_record()]
    store = LocalStore(tmp_path)
    append_scan(store, result)
    assert len(store.load_audit()) == 1 and len(store.load_runs()) == 1


def test_github_store_appends_audit_to_the_data_branch() -> None:
    repo = MagicMock(default_branch="main")
    not_found = type("NotFound", (Exception,), {"status": 404})
    repo.get_branch.return_value = SimpleNamespace()
    repo.get_contents.side_effect = not_found()
    store = GitHubBranchStore(repo, "driftpilot-data")
    store.append_audit([audit_record()], "msg")
    path, message, text = repo.create_file.call_args.args[:3]
    assert path == "history/audit.jsonl" and message == "msg" and text.count("\n") == 1

    existing = SimpleNamespace(decoded_content=(text).encode(), sha="s1")
    repo.get_contents.side_effect = None
    repo.get_contents.return_value = existing
    store.append_audit([audit_record("r2")], "msg2")
    args = repo.update_file.call_args.args
    assert args[0] == "history/audit.jsonl" and args[2].count("\n") == 2 and args[3] == "s1"


def test_verdict_guardrails_round_trip_and_default(load_fixture) -> None:
    from driftpilot.models import HistoryEvent

    [event, *_] = records_from_scan(scan(load_fixture("github/s2_required_approvals_reduced")))[0]
    assert event.verdict.guardrails == []
    event.verdict.guardrails = ["never-soften"]
    again = HistoryEvent.model_validate_json(event.model_dump_json())
    assert again.verdict.guardrails == ["never-soften"]
    old = json.loads(event.model_dump_json())
    del old["verdict"]["guardrails"]  # a line written before the field existed
    assert HistoryEvent.model_validate_json(json.dumps(old)).verdict.guardrails == []


def test_events_and_run_carry_context(tmp_path: Path, load_fixture) -> None:
    from driftpilot.config import Config, OwnershipConfig, TeamRule
    from driftpilot.scan import run_scan

    plan = FIXTURES_DIR / "github/s2_required_approvals_reduced.json"
    config = Config(
        ownership=OwnershipConfig(
            teams=[TeamRule(match="github_branch_protection.*", team="security")],
            environment="prod",
            repo="acme/infra",
        )
    )
    result = run_scan(tmp_path, config, plan_json=plan)
    events, run = records_from_scan(result)
    assert {e.context.team for e in events} == {"security"}
    assert events[0].context.environment == "prod" and events[0].context.repo == "acme/infra"
    assert (run.repo, run.environment, run.drift_type) == ("acme/infra", "prod", "infrastructure")
    assert sum(run.managed_by_team.values()) == run.managed_resource_count
    store = LocalStore(tmp_path / "h")
    append_scan(store, result)
    assert store.load_events()[0].context.team == "security"
    assert store.load_runs()[0].managed_by_team == run.managed_by_team


def test_run_record_counts_the_scan_errors(load_fixture) -> None:
    result = scan(load_fixture("github/batch_a_s2_s3_s5_s6_s7_s8"))
    assert records_from_scan(result)[1].errors == 0
    result.errors += ["event: bad file", "history: could not save"]
    assert records_from_scan(result)[1].errors == 2
