import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).parents[1] / "demo" / "console" / "backend.py"
spec = importlib.util.spec_from_file_location("console_backend", PATH)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


def test_report_lines_extracts_driftpilot_output() -> None:
    log = "\n".join(
        [
            "drift\tScan\t2026-10-25T06:55:52.1Z ##[group]Run driftpilot action",
            "drift\tScan\t2026-10-25T06:55:52.2Z driftpilot action",
            "drift\tScan\t2026-10-25T06:55:52.3Z ##[endgroup]",
            "drift\tScan\t2026-10-25T06:55:58.0Z No drift detected.",
            "drift\tScan\t2026-10-25T06:55:58.1Z ##[end-action id=x]",
            "drift\tScan\t2026-10-25T06:55:58.2Z Post job cleanup.",
        ]
    )
    assert backend.report_lines(log) == ["No drift detected."]


def test_driftpilot_items_only_new_and_marked() -> None:
    since = datetime(2026, 10, 25, 7, tzinfo=UTC)
    issues = [
        {"number": 1, "title": "old", "url": "u", "createdAt": "2026-10-25T06:00:00Z",
         "body": "<!-- driftpilot:key=a -->"},
        {"number": 2, "title": "new", "url": "u", "createdAt": "2026-10-25T07:01:00Z",
         "body": "<!-- driftpilot:key=b -->\nx"},
        {"number": 3, "title": "human", "url": "u", "createdAt": "2026-10-25T07:02:00Z",
         "body": "written by a person"},
    ]  # fmt: skip
    with patch.object(backend, "gh_json", side_effect=[issues, []]):
        items = backend.driftpilot_items(since)
    assert [i["number"] for i in items["issues"]] == [2] and items["prs"] == []


def test_collecting_output_keeps_proposals() -> None:
    from driftpilot.models import DriftFinding, Verdict
    from driftpilot.remediate.codify import Patch
    from driftpilot.remediate.github_out import Item
    from driftpilot.triage.policy import RemediationPlan

    finding = DriftFinding(
        id="f", run_id="r", detected_at=datetime(2026, 10, 25, tzinfo=UTC), provider="p",
        resource_type="docker_container", address="docker_container.web",
        change_kind="modified", attribute_path="memory", before=256, after=512,
    )  # fmt: skip
    verdict = Verdict(
        finding_id="f", source="llm", is_real_drift=True, severity="medium",
        category="availability", intent="likely_hotfix", recommended_action="codify",
        confidence=0.9, reason="r",
    )  # fmt: skip
    plan = RemediationPlan(
        key="codify:docker_container.web", address="docker_container.web", action="codify",
        delivery="pr", severity="medium", finding_ids=["f"],
    )  # fmt: skip
    item = Item(plan, [finding], [], {"f": verdict}, ".")
    out = backend.CollectingOutput()
    out.pull_request(item, Patch(True, {"main.tf": "x"}, "No changes.", 1, "codify-v2"))
    out.issue(item)
    assert [(p.kind, p.verified) for p in out.proposals] == [
        ("pull request", True),
        ("issue", False),
    ]
    assert "No changes." in out.proposals[0].body
