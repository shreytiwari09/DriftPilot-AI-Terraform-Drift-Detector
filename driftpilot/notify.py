"""Chat and webhook messages: new drift, a verdict-monitor alert, a failed scan.

Off unless the environment variable named in `notifications.webhook_env` holds an https URL. The
URL is a secret: it is read only from the environment and never printed, logged or put in an error
note (a failure is reported by its kind, for example `ConnectError`, or by the HTTP status).
Nothing here raises. Message text is built from data that is already redacted, cleaned with
`sanitize_text`, and capped in size. Findings are announced once: only those not seen in the
previous run of the same stream (a new episode) are included.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from driftpilot.config import NotificationsConfig
from driftpilot.guardrails import sanitize_text
from driftpilot.models import HistoryEvent
from driftpilot.ownership import mask_ids

TIMEOUT_SECONDS = 5.0
MAX_LISTED = 5  # findings named in one message; the rest are counted
SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class Notice:
    """One message: what happened, how serious, and a few detail lines."""

    event: str  # new_drift | monitor_alert | scan_failed
    severity: str
    title: str
    details: list[str] = field(default_factory=list)
    url: str = ""
    time: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class NotifyOutcome:
    sent: int = 0
    errors: list[str] = field(default_factory=list)  # short notes for the run's error list


def _clean(text: str, limit: int = 200) -> str:
    return sanitize_text(mask_ids(str(text)), limit)


def webhook_url(cfg: NotificationsConfig, env: Mapping[str, str] | None = None) -> str | None:
    """The webhook URL from the environment, or None when none is set or it is not https."""
    value = (os.environ if env is None else env).get(cfg.webhook_env, "").strip()
    if not value:
        return None
    parts = urlsplit(value)
    return value if parts.scheme == "https" and parts.hostname else None


def _is_set(cfg: NotificationsConfig, env: Mapping[str, str] | None) -> bool:
    return bool((os.environ if env is None else env).get(cfg.webhook_env, "").strip())


def new_events(before: list[HistoryEvent], after: list[HistoryEvent]) -> list[HistoryEvent]:
    """Events of this run whose finding was not in `before` (the previous run of the stream).

    A finding counts as seen when the same finding id with the same value was there. A value
    that changed is a new episode (the same rule as the history's episodes).
    """

    def key(e: HistoryEvent) -> tuple[str, str]:
        return e.finding.id, repr(getattr(e.finding, "after", None))

    seen = {key(e) for e in before}
    return [e for e in after if key(e) not in seen]


def _label(e: HistoryEvent, publish_addresses: bool) -> str:
    from driftpilot.report.dashboard.data import hide_address

    finding = e.finding
    address = getattr(finding, "address", None) or getattr(finding, "name", "resource")
    if not publish_addresses:
        address = hide_address(address)
    attribute = getattr(finding, "attribute_path", None)
    where = f"{address} {attribute}" if attribute else address
    return f"[{e.verdict.severity}] {_clean(where, 120)}"


def drift_notice(
    events: list[HistoryEvent],
    repo: str,
    drift_type: str,
    min_severity: str,
    publish_addresses: bool = True,
    url: str = "",
) -> Notice | None:
    """One message for the new findings at or above `min_severity`, or None when there are none."""
    floor = SEVERITY_RANK[min_severity]
    chosen = [e for e in events if SEVERITY_RANK.get(e.verdict.severity, 0) >= floor]
    if not chosen:
        return None
    chosen.sort(key=lambda e: -SEVERITY_RANK.get(e.verdict.severity, 0))
    counts: dict[str, int] = {}
    for e in chosen:
        counts[e.verdict.severity] = counts.get(e.verdict.severity, 0) + 1
    mix = ", ".join(f"{n} {s}" for s, n in counts.items())
    plural = "finding" if len(chosen) == 1 else "findings"
    details = [_label(e, publish_addresses) for e in chosen[:MAX_LISTED]]
    if len(chosen) > MAX_LISTED:
        details.append(f"and {len(chosen) - MAX_LISTED} more")
    return Notice(
        event="new_drift",
        severity=chosen[0].verdict.severity,
        title=f"DriftPilot: {len(chosen)} new drift {plural} in {_clean(repo, 80)} "
        f"({drift_type}): {mix}",
        details=details,
        url=url,
    )


def monitor_notice(alerts: list[str], url: str = "") -> Notice:
    return Notice(
        event="monitor_alert",
        severity="medium",
        title="DriftPilot: its own verdicts may be drifting (verdict monitor)",
        details=[_clean(a) for a in alerts[:3]],
        url=url,
    )


def failure_notice(repo: str, errors: list[str], url: str = "") -> Notice:
    return Notice(
        event="scan_failed",
        severity="high",
        title=f"DriftPilot: a scan for {_clean(repo, 80)} failed or reported "
        f"{len(errors)} error(s)",
        details=[_clean(e) for e in errors[:3]],
        url=url,
    )


def build_notices(
    cfg: NotificationsConfig,
    new: list[HistoryEvent],
    alerts: list[str],
    monitor_started: bool,
    repo: str,
    drift_type: str,
    publish_addresses: bool = True,
    url: str = "",
) -> list[Notice]:
    """The messages for one recorded run: new drift (at `min_severity`+), a monitor alert that
    just appeared. (A failed scan is announced separately, by `failure_notice`.)"""
    notices: list[Notice] = []
    drift = drift_notice(new, repo, drift_type, cfg.min_severity, publish_addresses, url)
    if drift is not None:
        notices.append(drift)
    if monitor_started and alerts:
        notices.append(monitor_notice(alerts, url))
    return notices


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def payload(fmt: str, notice: Notice) -> dict:
    """The JSON body for `slack` ({"text"}), `teams` ({"text"}) or `generic`."""
    lines = [notice.title, *[f"- {d}" for d in notice.details]]
    if fmt == "generic":
        return {
            "event": notice.event,
            "severity": notice.severity,
            "summary": "\n".join(lines),
            "url": notice.url,
            "time": notice.time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    link = [f"Details: {notice.url}"] if notice.url else []
    if fmt == "teams":
        return {"text": "\n\n".join([*lines, *link])}
    return {"text": _slack_escape("\n".join([*lines, *link]))}


def _redact(text: str, url: str | None) -> str:
    """Remove the webhook URL (and anything URL-shaped) from `text`."""
    if url:
        text = text.replace(url, "[webhook]")
    return re.sub(r"https?://\S+", "[url]", text)


def send(
    cfg: NotificationsConfig,
    notices: list[Notice],
    env: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
) -> NotifyOutcome:
    """Post each wanted notice to the webhook. Never raises; problems come back as notes."""
    outcome = NotifyOutcome()
    wanted = [n for n in notices if n.event in cfg.on]
    if not wanted or not _is_set(cfg, env):
        return outcome
    url = webhook_url(cfg, env)
    if url is None:
        outcome.errors.append(f"notify: ${cfg.webhook_env} is not an https URL, nothing was sent")
        return outcome
    own = client is None
    http = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    try:
        for notice in wanted:
            try:
                response = http.post(url, json=payload(cfg.format, notice))
            except Exception as e:  # never raise, never echo the message (it can hold the URL)
                outcome.errors.append(_redact(f"notify: {type(e).__name__}", url))
                continue
            if response.status_code >= 400:
                outcome.errors.append(f"notify: the webhook answered HTTP {response.status_code}")
            else:
                outcome.sent += 1
    finally:
        if own:
            http.close()
    return outcome
