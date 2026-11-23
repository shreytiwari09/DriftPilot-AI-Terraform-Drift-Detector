import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from driftpilot.cli import app
from driftpilot.scanners.docker import DockerScanner

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner(env={"COLUMNS": "200"})  # wide enough that rich doesn't wrap resource names


def test_scan_reports_critical_from_recorded_plan() -> None:
    plan = FIXTURES / "github/s2_required_approvals_reduced.json"
    result = runner.invoke(app, ["scan", "--plan-json", str(plan)])
    assert result.exit_code == 0
    assert "critical" in result.output
    assert "github_branch_protection.api_main" in result.output


def test_scan_json_output_hides_nothing() -> None:
    plan = FIXTURES / "docker/noise_mac_address_after_restart.json"
    result = runner.invoke(app, ["scan", "--plan-json", str(plan), "--json"])
    data = json.loads(result.stdout)
    assert data["findings"]
    assert all(not v["is_real_drift"] for v in data["verdicts"].values())


def test_fail_on_drift_exit_codes() -> None:
    drift = FIXTURES / "docker/s11_memory_changed.json"
    clean = FIXTURES / "docker/control_no_change.json"
    assert runner.invoke(app, ["scan", "--plan-json", str(drift), "--fail-on-drift"]).exit_code == 2
    assert runner.invoke(app, ["scan", "--plan-json", str(clean), "--fail-on-drift"]).exit_code == 0


def test_scan_with_scanner_and_recorded_state(tmp_path: Path) -> None:
    (tmp_path / ".driftpilot.yml").write_text("scanners:\n  docker: {}\n")
    fake = DockerScanner(client=None, managed_label="managed-by=terraform", ignore_names=[])
    handmade = {
        "provider": fake.provider,
        "resource_kind": "container",
        "resource_id": "f" * 64,
        "name": "driftpilot-handmade",
    }
    from driftpilot.models import ScannedResource

    with (
        patch("driftpilot.scan.build_scanners", return_value=[fake]),
        patch.object(DockerScanner, "list_resources", return_value=[ScannedResource(**handmade)]),
    ):
        result = runner.invoke(
            app,
            [
                "scan",
                "--dir", str(tmp_path),
                "--plan-json", str(FIXTURES / "docker/control_no_change.json"),
                "--state-json", str(FIXTURES / "docker/s13_state_for_scanner.json"),
            ],
        )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "driftpilot-handmade" in result.output


def test_terraform_error_exits_1(tmp_path: Path) -> None:
    from driftpilot.collector import TerraformError

    with patch("driftpilot.scan.terraform_init", side_effect=TerraformError("no creds")):
        result = runner.invoke(app, ["scan", "--dir", str(tmp_path)])
    assert result.exit_code == 1


def test_action_writes_summary_and_outputs(tmp_path: Path, monkeypatch) -> None:
    summary, outputs = tmp_path / "summary.md", tmp_path / "out.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setenv("DRIFTPILOT_WORKING_DIRECTORY", str(tmp_path))
    plan = json.loads((FIXTURES / "github/s2_required_approvals_reduced.json").read_text())
    with (
        patch("driftpilot.scan.terraform_init"),
        patch("driftpilot.scan.refresh_only_plan", return_value=plan),
    ):
        result = runner.invoke(app, ["action"])
    assert result.exit_code == 0, result.output
    assert "## DriftPilot drift report" in summary.read_text()
    assert "required_approving_review_count" in summary.read_text()
    assert "drift-found=true" in outputs.read_text()
    assert "critical-count=1" in outputs.read_text()
    assert "::error title=DriftPilot::1 critical" in result.output


LLM_ANSWER = json.dumps(
    {
        "verdicts": [
            {
                "attribute_path": path,
                "is_real_drift": True,
                "severity": "medium",
                "category": "availability",
                "intent": "likely_hotfix",
                "recommended_action": "codify",
                "confidence": 0.9,
                "reason": "Memory was raised by hand during an incident.",
            }
            for path in ("memory", "memory_swap")
        ]
    }
)


def test_scan_uses_llm_for_undecided_findings() -> None:
    from driftpilot.triage.llm import FakeLLM

    fake = FakeLLM([LLM_ANSWER])
    plan = FIXTURES / "docker/s11_memory_changed.json"
    with patch("driftpilot.cli.build_llm", return_value=fake):
        result = runner.invoke(app, ["scan", "--plan-json", str(plan)])
    assert result.exit_code == 0, result.output
    assert "codify" in result.output and "AI (triage-v3)" in result.output
    assert len(fake.prompts) == 1


def test_no_llm_flag_skips_triage() -> None:
    plan = FIXTURES / "docker/s11_memory_changed.json"
    with patch("driftpilot.cli.build_llm") as build:
        result = runner.invoke(app, ["scan", "--plan-json", str(plan), "--no-llm"])
    build.assert_not_called()
    assert "needs triage" in result.output


def test_action_opens_issue_for_critical(tmp_path: Path, monkeypatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("DRIFTPILOT_WORKING_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("DRIFTPILOT_GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "driftpilot-demo/infra")
    plan = json.loads((FIXTURES / "github/s2_required_approvals_reduced.json").read_text())
    output = MagicMock()
    output.issue.return_value = "https://github.com/driftpilot-demo/infra/issues/7"
    with (
        patch("driftpilot.scan.terraform_init"),
        patch("driftpilot.scan.refresh_only_plan", return_value=plan),
        patch("driftpilot.cli._github_output", return_value=output),
    ):
        result = runner.invoke(app, ["action"])
    assert result.exit_code == 0, result.output
    item = output.issue.call_args.args[0]
    assert (item.plan.action, item.plan.severity) == ("revert", "critical")
    assert "issues/7" in summary.read_text() and "### Fixes" in summary.read_text()


def test_scan_history_gets_an_audit_line_per_llm_call(tmp_path: Path) -> None:
    from driftpilot.history.store import LocalStore
    from driftpilot.triage.llm import FakeLLM

    fake = FakeLLM([LLM_ANSWER])
    plan = FIXTURES / "docker/s11_memory_changed.json"
    with patch("driftpilot.cli.build_llm", return_value=fake):
        result = runner.invoke(app, ["scan", "--plan-json", str(plan), "--history", str(tmp_path)])
    assert result.exit_code == 0, result.output
    [record] = LocalStore(tmp_path).load_audit()
    assert record.purpose == "triage" and record.prompt_version == "triage-v3" and record.valid
    assert "memory" not in record.model_dump_json()  # hashes only, never the prompt text


def test_action_summary_has_a_guardrails_section(tmp_path: Path, monkeypatch) -> None:
    from driftpilot.triage.llm import FakeLLM

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("DRIFTPILOT_WORKING_DIRECTORY", str(tmp_path))
    plan = json.loads((FIXTURES / "docker/s11_memory_changed.json").read_text())
    with (
        patch("driftpilot.scan.terraform_init"),
        patch("driftpilot.scan.refresh_only_plan", return_value=plan),
        patch("driftpilot.cli.build_llm", return_value=FakeLLM([LLM_ANSWER])),
    ):
        result = runner.invoke(app, ["action"])
    assert result.exit_code == 0, result.output
    assert "### Guardrails" in summary.read_text()
    assert "LLM calls: 1 of 60" in summary.read_text()


def test_console_survives_markup_like_text_in_values() -> None:
    from datetime import UTC, datetime

    from rich.console import Console

    from driftpilot.models import DriftFinding, ScanResult
    from driftpilot.report.console import print_result

    f = DriftFinding(
        id="f", run_id="r", detected_at=datetime(2026, 10, 25, tzinfo=UTC), provider="p",
        resource_type="t", address="t.x[/boom]", change_kind="modified",
        attribute_path="description", before="a", after="[/oops] [red]x[/red]",
    )  # fmt: skip
    result = ScanResult(run_id="r", started_at=f.detected_at, working_dir=".", findings=[f])
    console = Console(record=True, width=120)
    print_result(result, console)
    assert "[/oops]" in console.export_text()


def simulated_history(folder: Path) -> None:
    import importlib.util

    from driftpilot.history.store import LocalStore

    spec = importlib.util.spec_from_file_location(
        "simulate_history", Path(__file__).parents[1] / "scripts" / "simulate_history.py"
    )
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    events, runs = sim.simulate(seed=7, split=True)
    LocalStore(folder).save(events, runs, "sim")


def test_report_writes_page_data_and_csv(tmp_path: Path) -> None:
    import csv

    simulated_history(tmp_path / "h")
    out, csv_file = tmp_path / "site", tmp_path / "out" / "episodes.csv"
    result = runner.invoke(
        app,
        ["report", "--history", str(tmp_path / "h"), "--html", str(out), "--csv", str(csv_file)],
    )
    assert result.exit_code == 0, result.output
    assert (out / "index.html").exists()
    data = json.loads((out / "data.json").read_text())
    assert data["episodes"] and data["publishAddresses"] is True
    rows = list(csv.DictReader(csv_file.open()))
    assert len(rows) == len(data["episodes"]) and {"team", "repo", "driftType"} <= rows[0].keys()
    assert any(r["address"] == "docker_container.app3" for r in rows)


def test_report_hides_addresses_when_configured(tmp_path: Path) -> None:
    simulated_history(tmp_path / "h")
    config = tmp_path / "c.yml"
    config.write_text("dashboard:\n  publish_addresses: false\n")
    out = tmp_path / "site"
    args = ["report", "--history", str(tmp_path / "h"), "--html", str(out), "--config", str(config)]
    assert runner.invoke(app, args).exit_code == 0
    for name in ("index.html", "data.json"):
        assert "app3" not in (out / name).read_text()
