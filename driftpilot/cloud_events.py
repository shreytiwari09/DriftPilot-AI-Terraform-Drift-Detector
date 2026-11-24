"""Cloud audit events (AWS CloudTrail) as "who changed it" context for findings.

An event arrives as EventBridge delivers it (`detail` holds the CloudTrail record), as one raw
CloudTrail record, or as a CloudTrail log file (`Records`). Actor, event name, source, time and
request parameters are cleaned (the text is chosen by whoever made the call) and attached to
the findings on the matching resource. Matching is by name or ID only, so it is a strong hint
rather than proof.
"""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from driftpilot.guardrails import sanitize_text, sanitize_value
from driftpilot.models import ChangeContext, DriftFinding, UnmanagedFinding
from driftpilot.ownership import mask_accounts
from driftpilot.redact import redact

MAX_REQUEST_KEYS = 12
MAX_REQUEST_CHARS = 1500
_SECRET_KEY = re.compile(r"(?i)password|passwd|secret|token|credential|private_?key|session_?key")
_EVENT_ID_KEY = re.compile(r"(?i)^name$|(?:name|id|identifier|arn)$")  # request parameter keys
_RESOURCE_ID_KEY = re.compile(r"(?i)(?:^|_)(?:id|arn|name|identifier|bucket|user|role)$")


class CloudEvent(BaseModel):
    """A cleaned event plus the names and IDs it mentions (used to find the resource)."""

    context: ChangeContext
    identifiers: set[str] = set()


def _text(value: Any, limit: int = 120) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return mask_accounts(sanitize_text(value, limit))


def _actor(identity: dict[str, Any]) -> tuple[str | None, str | None]:
    kind = identity.get("type") if isinstance(identity.get("type"), str) else None
    arn = identity.get("arn")
    if kind == "Root":
        return "root", kind
    if isinstance(arn, str) and arn.startswith("arn:"):
        return _text(arn.split(":", 5)[-1]), kind  # "user/bob", "assumed-role/Admin/alice"
    name = identity.get("userName") or identity.get("invokedBy") or identity.get("principalId")
    return _text(name), kind


def _clean_request(params: Any) -> dict[str, Any]:
    """Request parameters without secrets or account IDs, short enough for a prompt."""
    if not isinstance(params, dict):
        return {}
    out: dict[str, Any] = {}
    size = 0
    for key, value in list(params.items())[:MAX_REQUEST_KEYS]:
        key = sanitize_text(str(key), 60)
        if _SECRET_KEY.search(key):
            value = "[redacted]"
        else:
            value = _mask(sanitize_value(redact(value), 300))
        size += len(json.dumps(value, default=str)) + len(key)
        if size > MAX_REQUEST_CHARS:
            out["_truncated"] = True
            break
        out[key] = value
    return out


def _mask(value: Any) -> Any:
    if isinstance(value, str):
        return mask_accounts(value)
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def _identifiers(detail: dict[str, Any]) -> set[str]:
    """Names and IDs the call mentions: id-like request parameters and the event's resources."""
    found: set[str] = set()

    def add(text: str) -> None:
        if 3 <= len(text) <= 256:
            found.add(text)
            if "/" in text or ":" in text:
                found.add(re.split(r"[/:]", text.rstrip("/:"))[-1])

    params = detail.get("requestParameters")
    for key, value in (params if isinstance(params, dict) else {}).items():
        if _EVENT_ID_KEY.search(str(key)) and isinstance(value, str):
            add(value)
    for res in detail.get("resources") or []:
        if isinstance(res, dict) and isinstance(res.get("ARN"), str):
            add(res["ARN"])
    return {i for i in found if len(i) >= 3}


def parse_event(raw: Any) -> CloudEvent | None:
    """One CloudEvent from an EventBridge event or a CloudTrail record; None for calls that
    changed nothing (read-only or failed) and for anything that is not an event."""
    if not isinstance(raw, dict):
        return None
    detail = raw.get("detail") if isinstance(raw.get("detail"), dict) else raw
    name = detail.get("eventName")
    if not isinstance(name, str) or detail.get("readOnly") is True or detail.get("errorCode"):
        return None
    identity = detail.get("userIdentity")
    actor, actor_type = _actor(identity if isinstance(identity, dict) else {})
    context = ChangeContext(
        actor=actor,
        actor_type=_text(actor_type, 40),
        event_name=_text(name, 80) or "unknown",
        event_source=_text(detail.get("eventSource"), 80),
        event_time=_text(detail.get("eventTime") or raw.get("time"), 40),
        request=_clean_request(detail.get("requestParameters")),
    )
    return CloudEvent(context=context, identifiers=_identifiers(detail))


def parse_events(text: str, source: str = "event") -> list[CloudEvent]:
    """Events from JSON text. Raises ValueError if it is not JSON or holds no CloudTrail event."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError(f"{source}: not valid JSON") from e
    if not isinstance(data, list | dict):
        raise ValueError(f"{source}: no CloudTrail event found (expected a JSON object)")
    items = data if isinstance(data, list) else data.get("Records", [data])
    parsed = [e for item in items if (e := parse_event(item))]
    if not parsed and not any(
        isinstance(i, dict) and ("eventName" in i or "eventName" in (i.get("detail") or {}))
        for i in items
    ):
        raise ValueError(f"{source}: no CloudTrail event found (expected eventName)")
    return parsed


def load_events(path: Path) -> list[CloudEvent]:
    """Read an event file (see `parse_events`)."""
    return parse_events(path.read_text(), str(path))


def _resource_ids(values: Any) -> set[str]:
    if not isinstance(values, dict):
        return set()
    return {
        v
        for k, v in values.items()
        if isinstance(v, str) and len(v) >= 3 and _RESOURCE_ID_KEY.search(str(k))
    }


def _latest(events: list[CloudEvent], ids: set[str]) -> ChangeContext | None:
    hits = [e for e in events if e.identifiers & ids]
    if not hits:
        return None
    return max(hits, key=lambda e: e.context.event_time or "").context


def attach_event_context(
    findings: list[DriftFinding],
    unmanaged: list[UnmanagedFinding],
    resources: dict[str, Any],
    events: list[CloudEvent],
) -> None:
    """Set `change_context` on findings (and unmanaged resources) that an event mentions."""
    if not events:
        return
    for f in findings:
        values = resources.get(f.address)
        ids = _resource_ids(values) | (_resource_ids(f.before) if values is None else set())
        f.change_context = _latest(events, ids)
    for u in unmanaged:
        u.change_context = _latest(events, {u.name, u.resource_id})
