"""The dashboard (SPEC §4.7): `index.html` plus `data.json`, built from drift history.

The page loads `data.json` from its own folder and re-fetches it every 5 minutes. A copy of the
same data is embedded in `index.html`, so opening the file straight from disk still works.
Chart.js comes from cdnjs (the only outside dependency).
"""

import html
import json
import re
from importlib import resources

import pandas as pd

from driftpilot.history.analytics import AnalyticsReport
from driftpilot.history.verdict_monitor import MonitorReport
from driftpilot.models import RunRecord
from driftpilot.report.dashboard.data import build_data

CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"


def render_page(data: dict) -> str:
    """The page with `data` embedded (`<` is escaped, so the data can't close the script tag)."""
    template = resources.files("driftpilot.report.dashboard").joinpath("template.html").read_text()
    embedded = json.dumps(data).replace("<", "\\u003c")
    values = {"TITLE": html.escape(data["title"]), "CHART_JS": CHART_JS, "DATA": embedded}
    return re.sub(r"__(TITLE|CHART_JS|DATA)__", lambda m: values[m.group(1)], template)


def build_dashboard(
    report: AnalyticsReport,
    monitor: MonitorReport,
    episodes: pd.DataFrame,
    runs: list[RunRecord],
    title: str = "DriftPilot dashboard",
    note: str | None = None,
    publish_addresses: bool = True,
) -> dict[str, str]:
    """The files to publish: `{"index.html": ..., "data.json": ...}`."""
    data = build_data(report, monitor, episodes, runs, title, note, publish_addresses)
    return {"index.html": render_page(data), "data.json": json.dumps(data, indent=1) + "\n"}
