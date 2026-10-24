import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from driftpilot.remediate.verify import trim_plan, verify_patch


def proc(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def workdir(tmp_path: Path) -> Path:
    d = tmp_path / "infra"
    (d / ".terraform").mkdir(parents=True, exist_ok=True)
    (d / "main.tf").write_text('resource "x" "a" {}\n')
    (d / "terraform.tfstate").write_text("{}")
    return d


def run_with(results):
    """Patch terraform so each call returns the next result; record args and cwd."""
    calls = []

    def fake(args, cwd, timeout):
        calls.append((args, cwd))
        return results.pop(0)

    return patch("driftpilot.remediate.verify.run_terraform", side_effect=fake), calls


def test_zero_change_plan_is_verified_and_original_untouched(tmp_path: Path) -> None:
    d = workdir(tmp_path)
    patcher, calls = run_with(
        [proc(0), proc(0), proc(0, "Refreshing state...\nNo changes. Your infrastructure matches.")]
    )
    with patcher:
        result = verify_patch(d, {"main.tf": 'resource "x" "a" { v = 1 }\n'})
    assert result.verified
    assert result.output == "No changes. Your infrastructure matches."
    assert result.files == {"main.tf": 'resource "x" "a" { v = 1 }\n'}
    assert [c[0][0] for c in calls] == ["fmt", "validate", "plan"]
    assert calls[0][1] != d  # ran in a temp copy
    assert (d / "main.tf").read_text() == 'resource "x" "a" {}\n'


def test_targets_limit_the_plan(tmp_path: Path) -> None:
    patcher, calls = run_with([proc(0), proc(0), proc(0, "No changes.")])
    with patcher:
        verify_patch(workdir(tmp_path), {"main.tf": "x"}, targets=["x.a"])
    assert "-target=x.a" in calls[2][0]


def test_plan_with_changes_is_not_verified(tmp_path: Path) -> None:
    patcher, _ = run_with([proc(0), proc(0), proc(2, "  ~ memory = 256 -> 512\nPlan: 0 to add")])
    with patcher:
        result = verify_patch(workdir(tmp_path), {"main.tf": "x"})
    assert not result.verified and "memory" in result.output


def test_validate_error_is_returned_for_feedback(tmp_path: Path) -> None:
    patcher, calls = run_with([proc(0), proc(1, stderr="Error: Unsupported argument")])
    with patcher:
        result = verify_patch(workdir(tmp_path), {"main.tf": "x"})
    assert (result.verified, result.stage) == (False, "validate")
    assert "Unsupported argument" in result.output
    assert len(calls) == 2


def test_import_only_plan(tmp_path: Path) -> None:
    import_json = {
        "resource_changes": [{"change": {"actions": ["no-op"], "importing": {"id": "x"}}}]
    }
    patcher, _ = run_with(
        [proc(0), proc(0), proc(2, "Plan: 1 to import, 0 to add"), proc(0, json.dumps(import_json))]
    )
    with patcher:
        assert verify_patch(workdir(tmp_path), {"imports.tf": "x"}, expect="import_only").verified

    update_json = {"resource_changes": [{"change": {"actions": ["update"], "importing": {}}}]}
    patcher, _ = run_with([proc(0), proc(0), proc(2, "Plan"), proc(0, json.dumps(update_json))])
    with patcher:
        assert not verify_patch(
            workdir(tmp_path), {"imports.tf": "x"}, expect="import_only"
        ).verified


def test_trim_plan_drops_refresh_noise_and_warning_boxes() -> None:
    text = (
        "x: Refreshing state... [id=1]\n\nNo changes. Your infrastructure matches.\n"
        "╷\n│ Warning: Resource targeting is in effect\n│ \n│ Do not use routinely.\n╵\n"
    )
    assert trim_plan(text) == "No changes. Your infrastructure matches."
