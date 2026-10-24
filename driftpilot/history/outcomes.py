"""Learn what humans did with DriftPilot's issues and PRs (SPEC §4.6 "human outcome").

accepted  = PR merged, or issue closed as completed
overruled = PR closed unmerged, issue closed as not planned or reopened,
            or its severity label changed
"""

import re
from typing import Any, Literal

from driftpilot.models import HistoryEvent

Outcome = Literal["accepted", "overruled", "pending"]
_NUMBER = re.compile(r"/(pull|issues)/(\d+)$")


def pr_outcome(pr: Any) -> Outcome:
    if pr.merged:
        return "accepted"
    return "overruled" if pr.state == "closed" else "pending"


def issue_outcome(issue: Any, severity: str) -> Outcome:
    labels = {label.name for label in issue.labels}
    if not any(name == f"severity:{severity}" for name in labels):
        return "overruled"  # a human changed (or removed) DriftPilot's severity label
    if issue.state == "closed":
        return "accepted" if issue.state_reason in (None, "completed") else "overruled"
    if issue.closed_at is not None:  # open again after being closed: the fix didn't hold
        return "overruled"
    return "pending"


def update_outcomes(events: list[HistoryEvent], repo: Any) -> int:
    """Fill in human_outcome for pending events linked to this repo's issues/PRs.

    Returns how many events changed.
    """
    cache: dict[str, Outcome] = {}
    changed = 0
    for event in events:
        r = event.remediation
        url = r and (r.pr_url or r.issue_url)
        if event.human_outcome != "pending" or not url or f"/{repo.full_name}/" not in url:
            continue
        if url not in cache:
            match = _NUMBER.search(url)
            if not match:
                continue
            kind, number = match.group(1), int(match.group(2))
            if kind == "pull":
                cache[url] = pr_outcome(repo.get_pull(number))
            else:
                cache[url] = issue_outcome(repo.get_issue(number), event.verdict.severity)
        if cache[url] != "pending":
            event.human_outcome = cache[url]
            changed += 1
    return changed
