"""Static HTML dashboard over drift history (SPEC §4.7).

One self-contained file built from `template.html`; Chart.js comes from cdnjs.
"""

import html
import json
from datetime import UTC, datetime
from importlib import resources
from string import Template

import pandas as pd

from driftpilot.history.analytics import AnalyticsReport
from driftpilot.history.verdict_monitor import OVERRULE_ALERT, MonitorReport

CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
SEVERITIES = ["critical", "high", "medium", "low"]


def _esc(value: object) -> str:
    return html.escape(str(value))


def _rows(cells_per_row: list[list[str]], empty: str, columns: int) -> str:
    if not cells_per_row:
        return f'<tr><td colspan="{columns}">{empty}</td></tr>'
    return "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in cells_per_row
    )


def _weekly_severity(episodes: pd.DataFrame) -> dict:
    if not len(episodes):
        return {"weeks": [], "series": {s: [] for s in SEVERITIES}}
    start = pd.to_datetime(episodes["start"], utc=True).dt.tz_localize(None)
    week = start.dt.to_period("W").dt.start_time.dt.date.astype(str)
    table = pd.crosstab(week, episodes["severity"]).reindex(columns=SEVERITIES, fill_value=0)
    return {
        "weeks": list(table.index),
        "series": {s: [int(v) for v in table[s]] for s in SEVERITIES},
    }


def _tile(label: str, value: object, hint: str = "") -> str:
    shown = "—" if value is None else value
    return (
        f'<div class="tile"><div class="value">{_esc(shown)}</div>'
        f'<div class="label">{_esc(label)}</div><div class="hint">{_esc(hint)}</div></div>'
    )


def build_dashboard(
    report: AnalyticsReport,
    monitor: MonitorReport,
    episodes: pd.DataFrame,
    title: str = "DriftPilot dashboard",
    note: str | None = None,
) -> str:
    h = report.health
    anomaly_days = {a.day for a in report.day_anomalies}
    data = {
        "days": [str(d) for d in report.daily_new_episodes],
        "daily": list(report.daily_new_episodes.values()),
        "anomalies": [
            n if d in anomaly_days else None for d, n in report.daily_new_episodes.items()
        ],
        "changePoints": [str(d) for d in report.change_points],
        "severity": _weekly_severity(episodes),
        "overrule": {
            "weeks": list(monitor.weekly_overrule_rate),
            "rates": [round(100 * r, 1) for r in monitor.weekly_overrule_rate.values()],
            "threshold": round(100 * OVERRULE_ALERT),
        },
    }
    hours = h.mean_hours_to_remediate
    ever = h.pct_resources_ever_drifted
    tiles = "".join(
        [
            _tile("Runs", h.runs),
            _tile("Drift episodes", report.episodes, "distinct times something drifted"),
            _tile("Runs with zero drift", f"{h.pct_runs_zero_drift}%"),
            _tile("Mean time to fix", None if hours is None else f"{hours} h"),
            _tile("Resources ever drifted", None if ever is None else f"{ever}%"),
            _tile("Monitor alerts", len(monitor.alerts), "is DriftPilot itself drifting?"),
        ]
    )
    recurring = _rows(
        [
            [
                f"<code>{_esc(r.address)}</code>",
                f"<code>{_esc(r.attribute or '—')}</code>",
                str(r.episodes),
            ]
            for r in sorted(report.recurring, key=lambda r: -r.episodes)
        ],
        "None.",
        3,
    )
    anomalies = _rows(
        [
            [_esc(a.day), str(a.new_episodes), str(a.baseline_mean), str(a.z)]
            for a in sorted(report.day_anomalies, key=lambda a: -a.z)
        ],
        "None.",
        4,
    )
    shifts = _rows(
        [
            [_esc(s.dimension), str(s.psi), _esc(s.chi2_p), "yes" if s.shifted else "no"]
            for s in report.shifts
        ],
        "Not enough data.",
        4,
    )
    period = ""
    if report.period_start and report.period_end:
        period = f"{report.period_start:%Y-%m-%d} → {report.period_end:%Y-%m-%d}"
    template = Template(
        resources.files("driftpilot.report.dashboard").joinpath("template.html").read_text()
    )
    return template.substitute(
        title=_esc(title),
        period=_esc(period),
        generated=f"{datetime.now(UTC):%Y-%m-%d %H:%M UTC}",
        banner=f'<p class="note">{_esc(note)}</p>' if note else "",
        tiles=tiles,
        alerts="".join(f"<li>{_esc(a)}</li>" for a in monitor.alerts) or "<li>None.</li>",
        recurring=recurring,
        anomalies=anomalies,
        shifts=shifts,
        chart_js=CHART_JS,
        data_json=json.dumps(data).replace("</", "<\\/"),
    )
