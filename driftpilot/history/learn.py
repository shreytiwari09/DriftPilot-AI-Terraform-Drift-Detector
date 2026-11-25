"""The "learn" step of a run: record history, update human outcomes, analyze, monitor, publish."""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from driftpilot.config import DashboardLinks
from driftpilot.history.analytics import AnalyticsReport, analyze, episodes_frame, stream_key
from driftpilot.history.outcomes import update_outcomes
from driftpilot.history.store import HistoryStore, records_from_scan
from driftpilot.history.verdict_monitor import MonitorReport, alert_issue_body, monitor_streams
from driftpilot.models import AuditRecord, HistoryEvent, RunRecord, ScanResult
from driftpilot.notify import new_events as new_events_since
from driftpilot.report.dashboard import build_site

MONITOR_KEY = "verdict-monitor:review"


@dataclass
class Learned:
    analytics: AnalyticsReport
    monitor: MonitorReport
    episodes: pd.DataFrame
    outcomes_updated: int
    runs: list[RunRecord]
    audit: list[AuditRecord] = field(default_factory=list)
    alert_url: str | None = None
    new_events: list[HistoryEvent] = field(default_factory=list)  # not in the stream's last run
    monitor_started: bool = False  # the monitor breached now and had not before this run


def learn(
    store: HistoryStore, result: ScanResult, repo: Any | None = None, output: Any | None = None
) -> Learned:
    """Append this run to history, refresh human outcomes (if `repo`), then analyze and monitor.

    With `output` (a GitHubOutput), a monitor breach opens or updates one review issue.
    """
    events, runs = store.load_events(), store.load_runs()
    updated = update_outcomes(events, repo) if repo is not None else 0
    new_events, run = records_from_scan(result)
    before = _previous_run_events(events, runs, run)
    was_breached = _breached_before(events, runs)
    events, runs = [*events, *new_events], [*runs, run]
    message = f"DriftPilot history: run {result.run_id} ({len(new_events)} event(s))"
    store.save(events, runs, message)
    store.append_audit(result.audit, message)

    report = analyze(events, runs)
    episodes = episodes_frame(events, runs)
    mon = monitor_streams(episodes, report.period_end)  # history now has at least this run
    learned = Learned(report, mon, episodes, updated, runs, store.load_audit())
    learned.new_events = new_events_since(before, new_events)
    learned.monitor_started = mon.breached and not was_breached
    if mon.breached and output is not None:
        learned.alert_url = output.alert(
            MONITOR_KEY,
            "[DriftPilot] Review rules or prompt: verdict quality may be drifting",
            alert_issue_body(mon),
        )
    return learned


def _previous_run_events(
    events: list[HistoryEvent], runs: list[RunRecord], run: RunRecord
) -> list[HistoryEvent]:
    """The events of the latest earlier run in the same stream as `run` (empty for a first run)."""
    mine = [r for r in runs if stream_key(r) == stream_key(run)]
    if not mine:
        return []
    last = max(mine, key=lambda r: r.timestamp).run_id
    return [e for e in events if e.run_id == last]


def _breached_before(events: list[HistoryEvent], runs: list[RunRecord]) -> bool:
    """Was the verdict monitor already breached on the history before this run?"""
    if not runs:
        return False
    now = max(r.timestamp for r in runs)
    return monitor_streams(episodes_frame(events, runs), now).breached


def dashboard_files(
    learned: Learned,
    title: str,
    note: str | None = None,
    publish_addresses: bool = True,
    links: DashboardLinks | None = None,
    llm_call_limit: int | None = 60,
    scan_every_hours: float = 6,
    sla_hours: dict[str, float | None] | None = None,
) -> dict[str, str]:
    """The app, `index.html` (data embedded) and `data.json`, ready to publish or write out."""
    return build_site(
        learned.analytics,
        learned.monitor,
        learned.episodes,
        learned.runs,
        title,
        note,
        publish_addresses,
        learned.audit,
        links,
        llm_call_limit,
        scan_every_hours,
        sla_hours,
    )


def publish_dashboard(files: dict[str, str], repo_name: str, token: str, message: str) -> str:
    """Write each file (the app, index.html, data.json) to the dashboard repo's default branch.

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
