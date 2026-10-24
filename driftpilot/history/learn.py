"""The "learn" step of a run: record history, update human outcomes, analyze, monitor, publish."""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from driftpilot.history.analytics import AnalyticsReport, analyze, episodes_frame
from driftpilot.history.outcomes import update_outcomes
from driftpilot.history.store import HistoryStore, records_from_scan
from driftpilot.history.verdict_monitor import MonitorReport, alert_issue_body, monitor
from driftpilot.models import ScanResult
from driftpilot.report.dashboard import build_dashboard

MONITOR_KEY = "verdict-monitor:review"


@dataclass
class Learned:
    analytics: AnalyticsReport
    monitor: MonitorReport
    episodes: pd.DataFrame
    outcomes_updated: int
    alert_url: str | None = None


def learn(
    store: HistoryStore, result: ScanResult, repo: Any | None = None, output: Any | None = None
) -> Learned:
    """Append this run to history, refresh human outcomes (if `repo`), then analyze and monitor.

    With `output` (a GitHubOutput), a monitor breach opens or updates one review issue.
    """
    events, runs = store.load_events(), store.load_runs()
    updated = update_outcomes(events, repo) if repo is not None else 0
    new_events, run = records_from_scan(result)
    events, runs = [*events, *new_events], [*runs, run]
    store.save(
        events, runs, f"DriftPilot history: run {result.run_id} ({len(new_events)} event(s))"
    )

    report = analyze(events, runs)
    episodes = episodes_frame(events, runs)
    mon = monitor(episodes, report.period_end)  # history now has at least this run
    learned = Learned(report, mon, episodes, updated)
    if mon.breached and output is not None:
        learned.alert_url = output.alert(
            MONITOR_KEY,
            "[DriftPilot] Review rules or prompt: verdict quality may be drifting",
            alert_issue_body(mon),
        )
    return learned


def dashboard_html(learned: Learned, title: str, note: str | None = None) -> str:
    return build_dashboard(learned.analytics, learned.monitor, learned.episodes, title, note)


def publish_dashboard(html: str, repo_name: str, token: str, message: str) -> str:
    """Write index.html to the dashboard repo's default branch (served by GitHub Pages)."""
    from github import Auth, Github

    repo = Github(auth=Auth.Token(token)).get_repo(repo_name)
    branch = repo.default_branch
    try:
        current = repo.get_contents("index.html", ref=branch)
        repo.update_file("index.html", message, html, current.sha, branch=branch)
    except Exception as e:
        if getattr(e, "status", None) != 404:
            raise
        repo.create_file("index.html", message, html, branch=branch)
    owner, name = repo_name.split("/", 1)
    return f"https://{owner}.github.io/{name}/"
