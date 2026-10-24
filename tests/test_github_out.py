from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from driftpilot.config import Config
from driftpilot.models import DriftFinding, ScanResult, Verdict
from driftpilot.remediate.codify import Patch
from driftpilot.remediate.github_out import GitHubOutput, Item, marker, revert_command
from driftpilot.remediate.runner import run_remediations
from driftpilot.triage.policy import RemediationPlan

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def finding(fid="f1", address="github_branch_protection.api_main", attr="required_status_checks"):
    return DriftFinding(
        id=fid,
        run_id="r",
        detected_at=NOW,
        provider="p",
        resource_type=address.split(".")[0],
        address=address,
        change_kind="modified",
        attribute_path=attr,
        before=[],
        after=[{"contexts": ["ci/hotfix-check"], "strict": False}],
    )


def verdict(fid="f1", action="codify", severity="medium") -> Verdict:
    return Verdict(
        finding_id=fid,
        source="llm",
        is_real_drift=True,
        severity=severity,
        category="availability",
        intent="likely_hotfix",
        recommended_action=action,
        confidence=0.9,
        reason="A required status check was added during an incident.",
        prompt_version="triage-v2",
    )


def item(action="codify", severity="medium", findings=None) -> Item:
    findings = findings or [finding()]
    plan = RemediationPlan(
        key=f"{action}:{findings[0].address}",
        address=findings[0].address,
        action=action,
        delivery="pr",
        severity=severity,
        finding_ids=[f.id for f in findings],
    )
    return Item(
        plan, findings, [], {f.id: verdict(f.id, action, severity) for f in findings}, "infra"
    )


def fake_repo(open_issues=()) -> MagicMock:
    repo = MagicMock()
    repo.get_labels.return_value = [SimpleNamespace(name="driftpilot")]
    repo.get_issues.return_value = list(open_issues)
    repo.get_branch.return_value.commit.sha = "abc"
    repo.create_issue.return_value.html_url = "https://gh/issues/1"
    repo.create_pull.return_value.html_url = "https://gh/pull/2"
    return repo


PATCH = Patch(
    True, {"main.tf": "resource ..."}, "No changes. Your infrastructure matches.", 1, "codify-v1"
)


def test_new_issue_with_labels_marker_and_revert_command() -> None:
    repo = fake_repo()
    out = GitHubOutput(repo, "main", "https://run/1")
    i = item("revert", "critical")
    assert out.issue(i) == "https://gh/issues/1"
    kwargs = repo.create_issue.call_args.kwargs
    assert (
        kwargs["title"] == "[DriftPilot] critical drift: github_branch_protection.api_main (revert)"
    )
    assert kwargs["labels"] == ["driftpilot", "severity:critical"]
    assert marker("revert:github_branch_protection.api_main") in kwargs["body"]
    assert "cd infra && terraform apply -target=github_branch_protection.api_main" in kwargs["body"]
    assert "https://run/1" in kwargs["body"]
    created = {c.args[0] for c in repo.create_label.call_args_list}
    assert "severity:critical" in created and "driftpilot" not in created


def test_existing_issue_is_updated_not_duplicated() -> None:
    old = MagicMock(
        body=marker("revert:github_branch_protection.api_main"), html_url="https://gh/9"
    )
    repo = fake_repo([old])
    assert GitHubOutput(repo, "main").issue(item("revert", "critical")) == "https://gh/9"
    repo.create_issue.assert_not_called()
    old.edit.assert_called_once()
    old.create_comment.assert_called_once()


def test_values_shown_as_json() -> None:
    from driftpilot.remediate.github_out import issue_body

    body = issue_body(item(), None, None)
    assert '`[]` → `[{"contexts": ["ci/hotfix-check"], "strict": false}]`' in body


def test_pull_request_creates_branch_file_and_pr_with_proof() -> None:
    from github import UnknownObjectException

    repo = fake_repo()
    repo.get_contents.side_effect = UnknownObjectException(404, "Not Found", None)
    url = GitHubOutput(repo, "main").pull_request(item(), PATCH)
    assert url == "https://gh/pull/2"
    repo.create_git_ref.assert_called_once_with(
        ref="refs/heads/driftpilot/codify-github-branch-protection-api-main", sha="abc"
    )
    path, message, content = repo.create_file.call_args.args
    assert (path, content) == ("infra/main.tf", "resource ...")
    body = repo.create_pull.call_args.kwargs["body"]
    assert "No changes. Your infrastructure matches." in body
    assert "run `terraform apply`" in body


def test_existing_file_is_updated_in_place() -> None:
    repo = fake_repo()
    repo.get_contents.return_value = SimpleNamespace(sha="old-sha")
    GitHubOutput(repo, "main").pull_request(item(), PATCH)
    assert repo.update_file.call_args.args[3] == "old-sha"


def test_revert_uses_replace_for_attributes_that_need_it() -> None:
    i = item("revert", findings=[finding("c", "docker_container.web", "cpu_shares")])
    assert revert_command(i, ".") == "terraform apply -replace=docker_container.web"


class RecordingOutput:
    def __init__(self) -> None:
        self.calls = []

    def issue(self, item, patch=None):
        self.calls.append(("issue", item.plan.key, patch))
        return "issue-url"

    def pull_request(self, item, patch):
        self.calls.append(("pr", item.plan.key, patch))
        return "pr-url"


@pytest.fixture
def scan_result() -> ScanResult:
    f = finding()
    return ScanResult(
        run_id="r", started_at=NOW, working_dir="infra", findings=[f], verdicts={f.id: verdict()}
    )


def test_runner_opens_pr_for_verified_codify(monkeypatch, scan_result, tmp_path) -> None:
    monkeypatch.setattr("driftpilot.remediate.runner.codify", lambda *a: PATCH)
    out = RecordingOutput()
    results = run_remediations(
        scan_result, Config(mode="open-prs"), object(), tmp_path, out, "infra"
    )
    assert out.calls[0][:2] == ("pr", "codify:github_branch_protection.api_main")
    assert results[0].pr_url == "pr-url" and results[0].verified


def test_runner_unverified_patch_becomes_issue(monkeypatch, scan_result, tmp_path) -> None:
    bad = Patch(False, {"main.tf": "x"}, "Error", 3, "codify-v1")
    monkeypatch.setattr("driftpilot.remediate.runner.codify", lambda *a: bad)
    out = RecordingOutput()
    results = run_remediations(scan_result, Config(mode="open-prs"), object(), tmp_path, out)
    assert out.calls[0][0] == "issue" and out.calls[0][2] is bad
    assert results[0].issue_url == "issue-url" and not results[0].verified


def test_runner_advise_mode_only_issues(scan_result, tmp_path) -> None:
    out = RecordingOutput()
    run_remediations(scan_result, Config(), object(), tmp_path, out)
    assert out.calls == [("issue", "codify:github_branch_protection.api_main", None)]


def test_runner_records_failures_and_continues(monkeypatch, scan_result, tmp_path) -> None:
    class Broken(RecordingOutput):
        def issue(self, item, patch=None):
            raise RuntimeError("GitHub is down")

    results = run_remediations(scan_result, Config(), object(), tmp_path, Broken())
    assert results == [] and "GitHub is down" in scan_result.errors[0]
