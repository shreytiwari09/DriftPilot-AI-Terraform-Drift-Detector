import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "inject_drift.py"
spec = importlib.util.spec_from_file_location("inject_drift", SCRIPT)
inject_drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inject_drift)


def test_all_14_scenarios_defined() -> None:
    assert sorted(inject_drift.SCENARIOS) == list(range(1, 15))


def test_list_needs_no_credentials(capsys) -> None:
    inject_drift.main(["list"])
    assert "Required approvals 2 -> 0" in capsys.readouterr().out


def test_inject_and_revert_approvals_call_the_api() -> None:
    branch = MagicMock()
    with patch.object(inject_drift, "main_branch", return_value=branch):
        inject_drift.main(["inject", "2"])
        inject_drift.main(["revert", "2"])
    calls = [c.kwargs["required_approving_review_count"] for c in branch.method_calls]
    assert calls == [0, 2]


def test_status_check_injection_keeps_current_approvals() -> None:
    branch = MagicMock()
    branch.get_required_pull_request_reviews.return_value.required_approving_review_count = 0
    with patch.object(inject_drift, "main_branch", return_value=branch):
        inject_drift.main(["inject", "5"])
    assert branch.edit_protection.call_args.kwargs["required_approving_review_count"] == 0


def test_unarchive_also_reenables_vulnerability_alerts() -> None:
    web = MagicMock()
    with patch.object(inject_drift, "repo", return_value=web):
        inject_drift.main(["revert", "4"])
    web.edit.assert_called_once_with(archived=False)
    web.enable_vulnerability_alert.assert_called_once()


def test_revert_needing_terraform_without_tf_dir_only_prints(capsys) -> None:
    with patch.object(inject_drift.subprocess, "run") as run:
        inject_drift.main(["revert", "10"])
    run.assert_not_called()
    assert "terraform apply" in capsys.readouterr().out
