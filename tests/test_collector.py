import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from driftpilot.collector import TerraformError, finding_id, parse_plan, refresh_only_plan
from driftpilot.redact import REDACTED

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def changes(findings):
    return {(f.address, f.attribute_path): (f.before, f.after) for f in findings}


def test_control_has_no_findings(load_fixture) -> None:
    assert parse_plan(load_fixture("docker/control_no_change"), "r1", NOW) == []
    assert parse_plan(load_fixture("github/control_no_change"), "r1", NOW) == []


def test_memory_change(load_fixture) -> None:
    findings = parse_plan(load_fixture("docker/s11_memory_changed"), "r1", NOW)
    assert changes(findings) == {
        ("docker_container.web", "memory"): (256, 512),
        ("docker_container.web", "memory_swap"): (512, 1024),
    }
    f = findings[0]
    assert f.change_kind == "modified"
    assert f.resource_type == "docker_container"
    assert f.provider == "registry.terraform.io/kreuzwerker/docker"


def test_restart_policy_change(load_fixture) -> None:
    findings = parse_plan(load_fixture("docker/s12_restart_policy_changed"), "r1", NOW)
    assert changes(findings) == {
        ("docker_container.web", "max_retry_count"): (0, 3),
        ("docker_container.web", "restart"): ("unless-stopped", "on-failure"),
    }


def test_deleted_container_is_one_finding(load_fixture) -> None:
    findings = parse_plan(load_fixture("docker/s10_container_removed"), "r1", NOW)
    assert len(findings) == 1
    f = findings[0]
    assert f.change_kind == "deleted"
    assert f.address == "docker_container.cache"
    assert f.attribute_path is None
    assert f.after is None


def test_github_nested_list_path(load_fixture) -> None:
    findings = parse_plan(load_fixture("github/s2_required_approvals_reduced"), "r1", NOW)
    assert changes(findings) == {
        (
            "github_branch_protection.api_main",
            "required_pull_request_reviews[0].required_approving_review_count",
        ): (2, 0)
    }


def test_list_length_change_is_one_finding(load_fixture) -> None:
    findings = parse_plan(load_fixture("docker/extra_container_stopped"), "r1", NOW)
    ports = [f for f in findings if f.attribute_path == "ports"]
    assert len(ports) == 1
    assert ports[0].after == []


def test_ids_are_stable() -> None:
    assert finding_id("a.b", "x") == finding_id("a.b", "x")
    assert finding_id("a.b", "x") != finding_id("a.b", "y")


def test_sensitive_values_redacted_but_change_still_seen() -> None:
    plan = {
        "resource_drift": [
            {
                "address": "x.db",
                "type": "x",
                "provider_name": "p",
                "change": {
                    "actions": ["update"],
                    "before": {"password": "old", "size": 1},
                    "after": {"password": "new", "size": 1},
                    "before_sensitive": {"password": True},
                    "after_sensitive": {"password": True},
                },
            }
        ]
    }
    [f] = parse_plan(plan, "r1", NOW)
    assert f.attribute_path == "password"
    assert (f.before, f.after, f.sensitive) == (REDACTED, REDACTED, True)


def _proc(code: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_plan_error_raises_with_stderr(tmp_path: Path) -> None:
    with (
        patch("driftpilot.collector.subprocess.run", return_value=_proc(1, stderr="bad creds")),
        pytest.raises(TerraformError, match="bad creds"),
    ):
        refresh_only_plan(tmp_path)


def test_plan_exit_2_is_ok(tmp_path: Path) -> None:
    results = [_proc(2), _proc(0, stdout='{"resource_drift": []}')]
    with patch("driftpilot.collector.subprocess.run", side_effect=results) as run:
        assert refresh_only_plan(tmp_path) == {"resource_drift": []}
    plan_args = run.call_args_list[0].args[0]
    assert plan_args[:3] == ["terraform", "plan", "-refresh-only"]
