import json
from pathlib import Path
from unittest.mock import patch

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
    data = json.loads(result.output)
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
