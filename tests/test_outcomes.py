from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from driftpilot.history.outcomes import issue_outcome, pr_outcome, update_outcomes
from driftpilot.models import DriftFinding, HistoryEvent, RemediationResult, Verdict

NOW = datetime(2026, 10, 25, tzinfo=UTC)
REPO = "driftpilot-demo/infra"


def labels(*names):
    return [SimpleNamespace(name=n) for n in names]


@pytest.mark.parametrize(
    ("merged", "state", "expected"),
    [(True, "closed", "accepted"), (False, "closed", "overruled"), (False, "open", "pending")],
)
def test_pr_outcome(merged, state, expected) -> None:
    assert pr_outcome(SimpleNamespace(merged=merged, state=state)) == expected


@pytest.mark.parametrize(
    ("state", "reason", "closed_at", "label", "expected"),
    [
        ("closed", "completed", NOW, "severity:critical", "accepted"),
        ("closed", "not_planned", NOW, "severity:critical", "overruled"),
        ("open", None, None, "severity:critical", "pending"),
        ("open", None, NOW, "severity:critical", "overruled"),  # reopened
        ("open", None, None, "severity:low", "overruled"),  # severity changed by a human
    ],
)
def test_issue_outcome(state, reason, closed_at, label, expected) -> None:
    issue = SimpleNamespace(
        state=state, state_reason=reason, closed_at=closed_at, labels=labels("driftpilot", label)
    )
    assert issue_outcome(issue, "critical") == expected


def event(url: str | None, outcome="pending") -> HistoryEvent:
    finding = DriftFinding(
        id="f",
        run_id="r",
        detected_at=NOW,
        provider="p",
        resource_type="t",
        address="t.a",
        change_kind="modified",
        attribute_path="x",
        before=1,
        after=2,
    )
    verdict = Verdict(
        finding_id="f",
        source="rule",
        is_real_drift=True,
        severity="critical",
        category="security",
        intent="unknown",
        recommended_action="revert",
        confidence=0.9,
        reason="r",
    )
    remediation = RemediationResult(
        finding_id="f", action="revert", verified=False, attempts=0, issue_url=url
    )
    return HistoryEvent(
        run_id="r",
        timestamp=NOW,
        finding=finding,
        verdict=verdict,
        remediation=remediation if url else None,
        human_outcome=outcome,
    )


def test_update_outcomes_checks_each_url_once() -> None:
    repo = MagicMock(full_name=REPO)
    repo.get_issue.return_value = SimpleNamespace(
        state="closed", state_reason="completed", closed_at=NOW, labels=labels("severity:critical")
    )
    url = f"https://github.com/{REPO}/issues/2"
    events = [
        event(url),
        event(url),
        event(None),
        event(url, "overruled"),
        event("https://github.com/other/repo/issues/1"),
    ]
    assert update_outcomes(events, repo) == 2
    assert [e.human_outcome for e in events] == [
        "accepted",
        "accepted",
        "pending",
        "overruled",
        "pending",
    ]
    repo.get_issue.assert_called_once_with(2)
