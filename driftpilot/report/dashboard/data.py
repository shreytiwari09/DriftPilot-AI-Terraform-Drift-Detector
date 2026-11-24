"""The dashboard's data: one JSON document, and the KPI maths behind the filters.

The page (`template.html`) loads this as `data.json`. `filter_episodes` and `compute_kpis` here are
the reference for the page's JavaScript, which does the same sums in the browser as filters change.
Percentages are 0-100 rounded to one decimal; hours too.
"""

import csv
import hashlib
import io
import json
import re
import shlex
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from driftpilot.config import DashboardLinks
from driftpilot.history.analytics import AnalyticsReport, stream_key
from driftpilot.history.verdict_monitor import OVERRULE_ALERT, MonitorReport
from driftpilot.models import AuditRecord, RunRecord
from driftpilot.ownership import mask_ids

SCHEMA = 1
RECURRING_MIN = 3  # episodes of the same setting before it counts as a recurring offender
FILTER_KEYS = [
    "from", "to", "team", "repo", "environment", "driftType", "severity", "status", "decidedBy",
    "outcome", "search",
]  # fmt: skip
CSV_COLUMNS = [
    "start", "resolvedAt", "address", "attribute", "resourceType", "team", "repo", "environment",
    "account", "driftType", "severity", "category", "action", "decidedBy", "outcome", "resolved",
    "runsSeen",
]  # fmt: skip


def iso(value: Any) -> str | None:
    """UTC timestamp as `2026-10-25T06:17:00Z` (sorts as text), or None for missing values."""
    if value is None or pd.isna(value):
        return None
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def hide_address(address: str) -> str:
    """A stable stand-in for an address (the same resource keeps the same label)."""
    return "resource-" + hashlib.sha256(address.encode()).hexdigest()[:10]


def _safe(value: Any) -> Any:
    return mask_ids(value) if isinstance(value, str) else value


def _text(value: Any, limit: int = 300) -> str | None:
    """Short, masked text for the detail drawer (None stays None)."""
    if value is None or (not isinstance(value, (list, dict, str)) and pd.isna(value)):
        return None
    text = value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)
    text = mask_ids(" ".join(text.split()))
    return text if len(text) <= limit else text[: limit - 1] + "…"


GITHUB_URL = re.compile(r"https://github\.com(/[A-Za-z0-9._~/%#?&=+-]*)?")


def safe_github_url(url: Any) -> str | None:
    """`url` if it is a plain https://github.com link (no login part, port or odd characters).

    Only these links ever become buttons on the page, so `javascript:` and look-alike hosts are
    dropped here, and the page checks them again.
    """
    ok = isinstance(url, str) and len(url) <= 300 and GITHUB_URL.fullmatch(url)
    return url if ok else None


def suggested_fix(address: str, attribute: str | None, before: Any, drift_type: str) -> str:
    """Text a person can copy to put a drifted setting back. DriftPilot never runs it."""
    if drift_type == "database":
        return (
            "-- Review first, then run by hand with a role that may change the schema.\n"
            "-- DriftPilot never changes a database.\n"
            f"-- Object: {_text(address, 120)}\n"
            f"-- Setting: {_text(attribute, 80) or 'the object itself'}\n"
            f"-- Expected (from the migration files): {_text(before, 120)}"
        )
    return (
        "# Review the plan first, then apply it yourself. DriftPilot never runs apply.\n"
        f"terraform plan -target={shlex.quote(address)}\n"
        f"terraform apply -target={shlex.quote(address)}"
    )


def _items(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def _number(value: Any) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _swap(text: Any, old: str, new: str) -> Any:
    return text.replace(old, new) if isinstance(text, str) else text


def episode_records(episodes: pd.DataFrame, publish_addresses: bool = True) -> list[dict]:
    """One dict per episode, camelCase, with account IDs and ARNs masked."""
    out = []
    for row in episodes.to_dict("records"):
        address = row["address"] if publish_addresses else hide_address(row["address"])
        attribute = None if pd.isna(row["attribute"]) else row["attribute"]
        out.append(
            {
                "id": row["finding_id"],
                "address": _safe(address),
                "attribute": _safe(attribute),
                "resourceType": row["resource_type"],
                "start": iso(row["start"]),
                "end": iso(row["end"]),
                "resolvedAt": iso(row["resolved_at"]),
                "runsSeen": int(row["runs_seen"]),
                "severity": row["severity"],
                "category": row["category"],
                "action": row["action"],
                "decidedBy": row["source"],
                "outcome": row["outcome"],
                "resolved": bool(row["resolved"]),
                "team": _safe(row["team"]),
                "repo": _safe(row["repo"]),
                "environment": _safe(row["environment"]),
                "account": _safe(row["account"]),
                "driftType": row["drift_type"],
                "reason": _text(_swap(row.get("reason"), row["address"], address), 600),
                "controls": _items(row.get("controls")),
                "guardrails": _items(row.get("guardrails")),
                "confidence": _number(row.get("confidence")),
                "ruleId": row.get("rule_id") if isinstance(row.get("rule_id"), str) else None,
                "promptVersion": row.get("prompt_version")
                if isinstance(row.get("prompt_version"), str)
                else None,
                "prUrl": safe_github_url(row.get("pr_url")),
                "issueUrl": safe_github_url(row.get("issue_url")),
                "before": _text(row.get("before"), 160),
                "after": _text(row.get("after"), 160),
                "fix": suggested_fix(address, attribute, row.get("before"), row["drift_type"])
                if row["action"] == "revert"
                else None,
            }
        )
    return out


def run_records(runs: list[RunRecord]) -> list[dict]:
    """What coverage and drift rate need: the last run of each day in each stream."""
    last: dict[tuple, RunRecord] = {}
    for r in sorted(runs, key=lambda r: r.timestamp):
        last[(*stream_key(r), r.timestamp.date())] = r
    return [
        {
            "t": iso(r.timestamp),
            "repo": _safe(r.repo),
            "environment": _safe(r.environment),
            "driftType": r.drift_type,
            "dir": Path(r.working_dir).name or ".",
            "managed": r.managed_resource_count,
            "unmanaged": r.unmanaged_count,
            "managedByTeam": r.managed_by_team,
            "unmanagedByTeam": r.unmanaged_by_team,
        }
        for r in sorted(last.values(), key=lambda r: r.timestamp)
    ]


def _in_range(t: str, f: dict) -> bool:
    day = t[:10]
    return (not f.get("from") or day >= f["from"]) and (not f.get("to") or day <= f["to"])


def filter_episodes(episodes: list[dict], f: dict) -> list[dict]:
    """The episodes that pass every filter in `f` (an empty value means "any")."""
    needle = (f.get("search") or "").strip().lower()
    status = f.get("status")
    keep = []
    for e in episodes:
        if not _in_range(e["start"], f):
            continue
        if any(f.get(k) and e[k] != f[k] for k in ("team", "repo", "environment", "driftType")):
            continue
        if any(f.get(k) and e[k] != f[k] for k in ("severity", "decidedBy", "outcome")):
            continue
        if status == "open" and e["resolved"]:
            continue
        if status == "resolved" and not e["resolved"]:
            continue
        if needle:
            hay = " ".join(
                str(e[k] or "") for k in ("address", "attribute", "resourceType", "team", "repo")
            )
            if needle not in hay.lower():
                continue
        keep.append(e)
    return keep


def _latest_per_stream(runs: list[dict], f: dict) -> list[dict]:
    latest: dict[tuple, dict] = {}
    for r in runs:
        if any(f.get(k) and r[k] != f[k] for k in ("repo", "environment", "driftType")):
            continue
        if not _in_range(r["t"], f):
            continue
        key = (r["repo"], r["environment"], r["driftType"], r["dir"])
        if key not in latest or r["t"] >= latest[key]["t"]:
            latest[key] = r
    return list(latest.values())


def _managed_and_unmanaged(runs: list[dict], f: dict) -> tuple[int | None, int | None]:
    """Resources in state and outside it, from the latest run of each stream (None = unknown)."""
    managed = unmanaged = 0
    team = f.get("team")
    latest = _latest_per_stream(runs, f)
    if not latest:
        return None, None
    for r in latest:
        if r["managed"] is None:
            return None, None
        if not team:
            managed += r["managed"]
            unmanaged += r["unmanaged"]
        elif r["managedByTeam"]:  # counted per team since this run
            managed += r["managedByTeam"].get(team, 0)
            unmanaged += r["unmanagedByTeam"].get(team, 0)
        else:
            return None, None
    return managed, unmanaged


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def compute_kpis(episodes: list[dict], runs: list[dict], f: dict, as_of: str | None) -> dict:
    """KPI values for the episodes and runs that pass the filters `f`."""
    eps = filter_episodes(episodes, f)
    managed, unmanaged = _managed_and_unmanaged(runs, f)
    drifted = len({e["address"] for e in eps})

    open_eps = [e for e in eps if not e["resolved"]]
    oldest = None
    if open_eps and as_of:
        age = pd.Timestamp(as_of) - pd.Timestamp(min(e["start"] for e in open_eps))
        oldest = round(age.total_seconds() / 3600, 1)

    durations = [
        (pd.Timestamp(e["resolvedAt"]) - pd.Timestamp(e["start"])).total_seconds() / 3600
        for e in eps
        if e["resolved"] and e["resolvedAt"]
    ]
    accepted = sum(e["outcome"] == "accepted" for e in eps)
    overruled = sum(e["outcome"] == "overruled" for e in eps)
    decided = accepted + overruled
    settings: dict[tuple, int] = {}
    for e in eps:
        key = (e["address"], e["attribute"])
        settings[key] = settings.get(key, 0) + 1

    return {
        "episodes": len(eps),
        "managed": managed,
        "unmanaged": unmanaged,
        "driftedResources": drifted,
        "iacCoverage": None if managed is None else _pct(managed, managed + unmanaged),
        "driftRate": None if not managed else _pct(drifted, managed),
        "openCount": len(open_eps),
        "oldestOpenHours": oldest,
        "mttrHours": round(sum(durations) / len(durations), 1) if durations else None,
        "decided": decided,
        "overruleRate": _pct(overruled, decided),
        "alertPrecision": _pct(accepted, decided),
        "recurringOffenders": sum(n >= RECURRING_MIN for n in settings.values()),
    }


REPO_PATTERN = re.compile(r"[\w.-]+/[\w.-]+")
WORKFLOW_PATTERN = re.compile(r"[\w.-]+\.ya?ml")
BRANCH_PATTERN = re.compile(r"[\w][\w./-]*")
DEFAULT_WORKFLOW, DEFAULT_BRANCH = "driftpilot.yml", "main"


def build_links(configured: DashboardLinks | None, episodes: list[dict]) -> dict:
    """The names behind the page's action buttons (repo, workflow file, branch), each checked.

    The repo defaults to the one in most episodes. Values that fail their pattern become None, and
    the page hides the buttons that need them. The page builds the GitHub URLs itself.
    """
    given = configured or DashboardLinks()
    seen = Counter(e["repo"] for e in episodes if REPO_PATTERN.fullmatch(e["repo"] or ""))
    repo = given.repo or (seen.most_common(1)[0][0] if seen else None)

    def valid(value: str | None, pattern: re.Pattern) -> str | None:
        return value if value and pattern.fullmatch(value) and ".." not in value else None

    return {
        "repo": valid(repo, REPO_PATTERN),
        "workflow": valid(given.workflow or DEFAULT_WORKFLOW, WORKFLOW_PATTERN),
        "branch": valid(given.branch or DEFAULT_BRANCH, BRANCH_PATTERN),
    }


def guardrail_data(
    audit: list[AuditRecord] | None, runs: list[RunRecord], limit: int | None
) -> dict:
    """LLM calls and guardrail events per run, for the Guardrails page (empty without an audit)."""
    where = {r.run_id: r for r in runs}
    per_run: dict[str, dict] = {}
    for a in sorted(audit or [], key=lambda a: a.timestamp):
        run = where.get(a.run_id)
        row = per_run.setdefault(
            a.run_id,
            {
                "runId": a.run_id,
                "t": iso(a.timestamp),
                "repo": _safe(run.repo) if run else "unknown",
                "environment": _safe(run.environment) if run else "unknown",
                "driftType": run.drift_type if run else "infrastructure",
                "calls": 0,
                "invalid": 0,
                "events": {},
            },
        )
        row["calls"] += 1
        row["invalid"] += not a.valid
        for ev in a.guardrail_events:
            row["events"][ev.kind] = row["events"].get(ev.kind, 0) + 1
    return {"llmCallLimit": limit, "hasAudit": bool(audit), "runs": list(per_run.values())}


def _analytics(report: AnalyticsReport, publish_addresses: bool) -> dict:
    anomaly_days = {a.day for a in report.day_anomalies}
    daily = report.daily_new_episodes
    return {
        "days": [str(d) for d in daily],
        "daily": list(daily.values()),
        "anomalies": [n if d in anomaly_days else None for d, n in daily.items()],
        "changePoints": [str(d) for d in report.change_points],
        "recurring": [
            {
                "address": _safe(r.address if publish_addresses else hide_address(r.address)),
                "attribute": _safe(r.attribute),
                "episodes": r.episodes,
            }
            for r in sorted(report.recurring, key=lambda r: -r.episodes)
        ],
        "dayAnomalies": [
            {"day": str(a.day), "newEpisodes": a.new_episodes, "usual": a.baseline_mean, "z": a.z}
            for a in sorted(report.day_anomalies, key=lambda a: -a.z)
        ],
        "shifts": [
            {"dimension": s.dimension, "psi": s.psi, "chi2p": s.chi2_p, "shifted": s.shifted}
            for s in report.shifts
        ],
        "health": report.health.model_dump(),
    }


def build_data(
    report: AnalyticsReport,
    monitor: MonitorReport,
    episodes: pd.DataFrame,
    runs: list[RunRecord],
    title: str = "DriftPilot dashboard",
    note: str | None = None,
    publish_addresses: bool = True,
    generated: datetime | None = None,
    audit: list[AuditRecord] | None = None,
    links: DashboardLinks | None = None,
    llm_call_limit: int | None = 60,
) -> dict:
    """Everything the page needs, as plain JSON-able values."""
    records = episode_records(episodes, publish_addresses)
    run_rows = run_records(runs)
    as_of = run_rows[-1]["t"] if run_rows else None
    return {
        "schema": SCHEMA,
        "title": title,
        "note": note,
        "generated": iso(generated or datetime.now(UTC)),
        "asOf": as_of,
        "periodStart": iso(report.period_start),
        "periodEnd": iso(report.period_end),
        "publishAddresses": publish_addresses,
        "episodes": records,
        "runs": run_rows,
        "kpis": compute_kpis(records, run_rows, {}, as_of),
        "analytics": _analytics(report, publish_addresses),
        "links": build_links(links, records),
        "guardrails": guardrail_data(audit, runs, llm_call_limit),
        "monitor": {
            "alerts": monitor.alerts,
            "overruleThreshold": round(100 * OVERRULE_ALERT),
            "recentOverruleRate": monitor.recent_overrule_rate,
            "baselineOverruleRate": monitor.baseline_overrule_rate,
        },
    }


def _csv_cell(value: Any) -> str:
    """Cell text; a leading `=`, `+`, `-` or `@` gets a quote so spreadsheets don't run it."""
    text = "" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def episodes_csv(episodes: list[dict]) -> str:
    """The episodes as CSV text (what `driftpilot report --csv` and the page's button write)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for e in episodes:
        writer.writerow([_csv_cell(e[c]) for c in CSV_COLUMNS])
    return out.getvalue()
