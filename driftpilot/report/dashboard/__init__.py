"""The dashboard (SPEC §4.7): a static web app plus `data.json`, built from drift history.

The app is a React build kept in `app/` (source in the repo's `dashboard/` folder, so users need no
Node). It loads `data.json` from its own folder and re-fetches it every 5 minutes. A copy of the
same data is embedded in `index.html`, so opening the file straight from disk still works.
If `app/` is missing, `build_site` falls back to the older single-file page (`build_dashboard`,
Chart.js from cdnjs).
"""

import html
import json
import re
from importlib import resources
from importlib.resources.abc import Traversable

import pandas as pd

from driftpilot.config import DashboardLinks
from driftpilot.history.analytics import AnalyticsReport
from driftpilot.history.verdict_monitor import MonitorReport
from driftpilot.models import AuditRecord, RunRecord
from driftpilot.report.dashboard.data import build_data
from driftpilot.report.metrics import build_metrics

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
    """The files to publish: `index.html`, `data.json` and `metrics.prom`."""
    data = build_data(report, monitor, episodes, runs, title, note, publish_addresses)
    text = json.dumps(data, separators=(",", ":")) + "\n"
    return {"index.html": render_page(data), "data.json": text, "metrics.prom": build_metrics(data)}


def _read_tree(folder: Traversable, prefix: str = "") -> dict[str, str]:
    files: dict[str, str] = {}
    for item in sorted(folder.iterdir(), key=lambda i: i.name):
        if item.is_dir():
            files.update(_read_tree(item, f"{prefix}{item.name}/"))
        else:
            files[f"{prefix}{item.name}"] = item.read_text(encoding="utf-8")
    return files


def app_files() -> dict[str, str] | None:
    """The built React app (path -> text), or None when `app/index.html` is not there."""
    folder = resources.files("driftpilot.report.dashboard").joinpath("app")
    if not folder.is_dir() or not folder.joinpath("index.html").is_file():
        return None
    return _read_tree(folder)


def render_app_page(index_html: str, data: dict) -> str:
    """The app's `index.html` with the data (and title) embedded, for opening from disk."""
    embedded = json.dumps(data).replace("<", "\\u003c")
    return index_html.replace("__DRIFTPILOT_TITLE__", html.escape(data["title"])).replace(
        "__DRIFTPILOT_DATA__", embedded
    )


def build_site(
    report: AnalyticsReport,
    monitor: MonitorReport,
    episodes: pd.DataFrame,
    runs: list[RunRecord],
    title: str = "DriftPilot dashboard",
    note: str | None = None,
    publish_addresses: bool = True,
    audit: list[AuditRecord] | None = None,
    links: DashboardLinks | None = None,
    llm_call_limit: int | None = 60,
    scan_every_hours: float = 6,
    sla_hours: dict[str, float | None] | None = None,
) -> dict[str, str]:
    """Every file to publish: the React app, `index.html` with data embedded, `data.json` and
    `metrics.prom`.

    Falls back to the older single-file page when the app was not built.
    """
    app = app_files()
    if app is None:
        return build_dashboard(report, monitor, episodes, runs, title, note, publish_addresses)
    data = build_data(
        report, monitor, episodes, runs, title, note, publish_addresses, None, audit, links,
        llm_call_limit, scan_every_hours, sla_hours,
    )  # fmt: skip
    text = json.dumps(data, separators=(",", ":")) + "\n"
    return {
        **app,
        "index.html": render_app_page(app["index.html"], data),
        "data.json": text,
        "metrics.prom": build_metrics(data),
    }
