import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from driftpilot.collector import parse_plan, resource_values
from driftpilot.history.learn import MONITOR_KEY, learn, publish_dashboard
from driftpilot.history.store import LocalStore
from driftpilot.models import ScanResult
from driftpilot.triage.rules import apply_rules, load_rules

SCRIPT = Path(__file__).parents[1] / "scripts" / "simulate_history.py"
spec = importlib.util.spec_from_file_location("simulate_history", SCRIPT)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)
NOW = datetime(2026, 10, 25, 6, tzinfo=UTC)


def scan(load_fixture) -> ScanResult:
    plan = load_fixture("github/s2_required_approvals_reduced")
    findings = parse_plan(plan, "live-1", NOW)
    return ScanResult(
        run_id="live-1",
        started_at=NOW,
        working_dir="infra",
        findings=findings,
        verdicts=apply_rules(findings, load_rules(), resource_values(plan)),
    )


def test_learn_appends_and_opens_monitor_issue(tmp_path, load_fixture) -> None:
    store = LocalStore(tmp_path)
    events, runs = sim.simulate(seed=7)
    store.save(events, runs, "seed")
    output = MagicMock()
    output.alert.return_value = "https://gh/issues/9"

    learned = learn(store, scan(load_fixture), repo=None, output=output)

    assert len(store.load_runs()) == len(runs) + 1
    assert len(store.load_events()) == len(events) + 1
    assert learned.monitor.breached and learned.alert_url == "https://gh/issues/9"
    assert output.alert.call_args.args[0] == MONITOR_KEY


def test_learn_without_history_or_output(tmp_path, load_fixture) -> None:
    learned = learn(LocalStore(tmp_path), scan(load_fixture))
    assert learned.analytics.health.runs == 1 and not learned.monitor.breached


def test_publish_dashboard_creates_index() -> None:
    not_found = type("NotFound", (Exception,), {"status": 404})
    repo = MagicMock(default_branch="main")
    repo.get_contents.side_effect = not_found()
    with patch("github.Github") as gh:
        gh.return_value.get_repo.return_value = repo
        url = publish_dashboard("<html>", "driftpilot-demo/drift-dashboard", "t", "msg")
    assert url == "https://driftpilot-demo.github.io/drift-dashboard/"
    repo.create_file.assert_called_once_with("index.html", "msg", "<html>", branch="main")
