"""The "learn" step of a run: record history, update human outcomes, analyze, monitor, publish."""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from driftpilot.history.analytics import AnalyticsReport, analyze, episodes_frame
from driftpilot.history.outcomes import update_outcomes
from driftpilot.history.store import HistoryStore, records_from_scan
from driftpilot.history.verdict_monitor import MonitorReport, alert_issue_body, monitor
from driftpilot.models import RunRecord, ScanResult
from driftpilot.report.dashboard import build_dashboard

MONITOR_KEY = "verdict-monitor:review"


@dataclass
class Learned:
    analytics: AnalyticsReport
    monitor: MonitorReport
    episodes: pd.DataFrame
    outcomes_updated: int
    runs: list[RunRecord]
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
    message = f"DriftPilot history: run {result.run_id} ({len(new_events)} event(s))"
    store.save(events, runs, message)
    store.append_audit(result.audit, message)

    report = analyze(events, runs)
    episodes = episodes_frame(events, runs)
    mon = monitor(episodes, report.period_end)  # history now has at least this run
    learned = Learned(report, mon, episodes, updated, runs)
    if mon.breached and output is not None:
        learned.alert_url = output.alert(
            MONITOR_KEY,
            "[DriftPilot] Review rules or prompt: verdict quality may be drifting",
            alert_issue_body(mon),
        )
    return learned


def dashboard_files(
    learned: Learned, title: str, note: str | None = None, publish_addresses: bool = True
) -> dict[str, str]:
    """`index.html` and `data.json`, ready to publish or write to a folder."""
    return build_dashboard(
        learned.analytics,
        learned.monitor,
        learned.episodes,
        learned.runs,
        title,
        note,
        publish_addresses,
    )


def publish_dashboard(files: dict[str, str], repo_name: str, token: str, message: str) -> str:
    """Write each file (index.html, data.json) to the dashboard repo's default branch.

    GitHub Pages serves it. Not run against GitHub by tests; they use a fake repo.
    """
    from github import Auth, Github

    repo = Github(auth=Auth.Token(token)).get_repo(repo_name)
    branch = repo.default_branch
    for path, text in files.items():
        try:
            current = repo.get_contents(path, ref=branch)
        except Exception as e:
            if getattr(e, "status", None) != 404:
                raise
            current = None
        if current is None:
            repo.create_file(path, message, text, branch=branch)
        elif current.decoded_content.decode() != text:
            repo.update_file(path, message, text, current.sha, branch=branch)
    owner, name = repo_name.split("/", 1)
    return f"https://{owner}.github.io/{name}/"
