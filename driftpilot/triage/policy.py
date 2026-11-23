"""Policy: fixed rules that have the final say after rules and the LLM (SPEC §4.4 step 3)."""

from functools import cache
from typing import Any

from pydantic import BaseModel

from driftpilot.config import Config
from driftpilot.guardrails import injection_signals
from driftpilot.models import (
    SEVERITY_RANK,
    Action,
    DriftFinding,
    GuardrailEvent,
    Severity,
    UnmanagedFinding,
    Verdict,
)
from driftpilot.triage.rules import NeverSoften, glob_match, load_never_soften, never_soften_for

PR_ACTIONS = {"codify", "ignore_changes", "import"}
SOFT_ACTIONS = {"codify", "ignore_changes", "none"}  # actions that accept or hide a change


def _target(f: DriftFinding) -> str:
    return f"{f.address}.{f.attribute_path}" if f.attribute_path else f.address


def _with(verdict: Verdict, note: str, **changes) -> Verdict:
    return verdict.model_copy(
        update={"source": "policy", "reason": f"{verdict.reason} ({note})", **changes}
    )


def unmanaged_verdict(u: UnmanagedFinding) -> Verdict:
    return Verdict(
        finding_id=u.id,
        source="policy",
        is_real_drift=True,
        severity="medium",
        category="security",
        intent="unknown",
        recommended_action="import",
        confidence=1.0,
        reason=(
            f"The {u.resource_kind} '{u.name}' exists but is not managed by Terraform, so nobody "
            "reviews its settings. Import it so it is tracked like everything else."
        ),
    )


@cache
def _never_soften_list() -> list[NeverSoften]:
    return load_never_soften()


def _never_soften(
    f: DriftFinding, v: Verdict, resource: Any, events: list[GuardrailEvent]
) -> Verdict:
    """An LLM verdict softer than the floor for a known security weakening is overridden.

    The model can still be stricter (higher severity, investigate); never softer.
    """
    entry = never_soften_for(f, _never_soften_list(), resource)
    if entry is None or v.source != "llm":
        return v
    floor = entry.floor_severity
    soft = (
        not v.is_real_drift
        or SEVERITY_RANK[v.severity] < SEVERITY_RANK[floor]
        or v.recommended_action in SOFT_ACTIONS
    )
    if not soft:
        return v
    events.append(GuardrailEvent(kind="never-soften", finding_id=f.id, detail=entry.reason))
    keep_action = v.is_real_drift and v.recommended_action in ("revert", "recreate", "investigate")
    return _with(
        v,
        f"guardrail: never-soften ({entry.reason})",
        is_real_drift=True,
        severity=max(v.severity, floor, key=SEVERITY_RANK.__getitem__),
        recommended_action=v.recommended_action if keep_action else "revert",
        guardrails=[*v.guardrails, "never-soften"],
    )


def _signals_by_address(findings: list[DriftFinding]) -> dict[str, list[str]]:
    """Injection signals per resource: the model reads a resource's changes together, so text in
    one change can steer its verdict on a sibling change."""
    out: dict[str, list[str]] = {}
    for f in findings:
        for name in injection_signals([f.address, f.attribute_path, f.before, f.after]):
            if name not in out.setdefault(f.address, []):
                out[f.address].append(name)
    return out


def _suspicious(
    f: DriftFinding,
    v: Verdict,
    events: list[GuardrailEvent],
    by_rule_or_llm: bool,
    signals: list[str],
) -> Verdict:
    """Text that looks like an injection attempt can never make a change "not real" or "none"."""
    if not signals or not by_rule_or_llm:
        return v
    events.append(
        GuardrailEvent(kind="suspicious-input", finding_id=f.id, detail=", ".join(signals))
    )
    changes: dict[str, Any] = {"guardrails": [*v.guardrails, "suspicious-input"]}
    if not v.is_real_drift or v.recommended_action in SOFT_ACTIONS:
        changes |= {"is_real_drift": True, "recommended_action": "investigate"}
        if not v.is_real_drift:
            changes["severity"] = max(v.severity, "medium", key=SEVERITY_RANK.__getitem__)
    note = f"guardrail: suspicious input ({', '.join(signals)}); a person should review it"
    return _with(v, note, **changes)


def apply_policy(
    findings: list[DriftFinding],
    unmanaged: list[UnmanagedFinding],
    verdicts: dict[str, Verdict],
    config: Config,
    resources: dict[str, Any] | None = None,
    events: list[GuardrailEvent] | None = None,
) -> dict[str, Verdict]:
    """Return verdicts with config ignores, guardrails, severity overrides and the confidence floor.

    `resources` (drifted resources by address) gives rules like open-admin-port their context;
    `events` collects what the guardrails did.
    """
    out = dict(verdicts)
    resources = resources or {}
    events = events if events is not None else []
    guard = config.guardrails.enabled
    signals = _signals_by_address(findings) if guard else {}
    for f in findings:
        v = out.get(f.id)
        if v is None:
            continue
        if any(glob_match(p, _target(f)) or glob_match(p, f.address) for p in config.ignore):
            out[f.id] = _with(
                v,
                "ignored by .driftpilot.yml",
                is_real_drift=False,
                severity="none",
                recommended_action="none",
            )
            continue
        if guard:
            by_rule_or_llm = v.source in ("rule", "llm")
            v = _never_soften(f, v, resources.get(f.address), events)
            v = _suspicious(f, v, events, by_rule_or_llm, signals.get(f.address, []))
        for override in config.severity_overrides:
            type_ok = glob_match(override.match.get("type", "*"), f.resource_type)
            attr_ok = glob_match(override.match.get("attribute", "*"), f.attribute_path or "")
            if type_ok and attr_ok and v.is_real_drift:
                v = _with(
                    v, f"severity set to {override.severity} by config", severity=override.severity
                )
                break
        if (
            v.is_real_drift
            and v.recommended_action not in ("investigate", "none")
            and v.confidence < config.confidence_threshold
        ):
            v = _with(
                v,
                f"confidence {v.confidence:.2f} below {config.confidence_threshold}",
                recommended_action="investigate",
            )
        out[f.id] = v
    for u in unmanaged:
        if u.id in out:
            continue
        v = unmanaged_verdict(u)
        if guard and (signals := injection_signals([u.name, u.resource_kind])):
            events.append(
                GuardrailEvent(kind="suspicious-input", finding_id=u.id, detail=", ".join(signals))
            )
            v = _with(
                v,
                f"guardrail: suspicious input ({', '.join(signals)}); a person should review it",
                recommended_action="investigate",
                guardrails=["suspicious-input"],
            )
        out[u.id] = v
    return out


class RemediationPlan(BaseModel):
    """One issue or PR: an action on one resource (all its findings together)."""

    key: str  # de-duplication key, e.g. "codify:github_branch_protection.api_main"
    address: str
    action: Action
    delivery: str  # "issue" or "pr"
    severity: Severity
    finding_ids: list[str]


def resolve_action(actions: list[Action]) -> Action:
    """One action per resource.

    All findings agree → that action; any revert/recreate → it (safety first); else investigate.
    """
    unique = set(actions)
    if len(unique) == 1:
        return actions[0]
    for safe in ("revert", "recreate"):
        if safe in unique:
            return safe
    return "investigate"


def plan_remediations(
    findings: list[DriftFinding],
    unmanaged: list[UnmanagedFinding],
    verdicts: dict[str, Verdict],
    config: Config,
) -> list[RemediationPlan]:
    by_address: dict[str, list[DriftFinding]] = {}
    for f in findings:
        v = verdicts.get(f.id)
        if v and v.is_real_drift and v.recommended_action != "none":
            by_address.setdefault(f.address, []).append(f)

    items: list[tuple[str, Action, Severity, list[str]]] = []
    for address, group in by_address.items():
        group_verdicts = [verdicts[f.id] for f in group]
        action = resolve_action([v.recommended_action for v in group_verdicts])
        severity = max((v.severity for v in group_verdicts), key=SEVERITY_RANK.__getitem__)
        items.append((address, action, severity, [f.id for f in group]))
    for u in unmanaged:
        v = verdicts[u.id]
        items.append((f"{u.resource_kind}:{u.name}", v.recommended_action, v.severity, [u.id]))

    plans = []
    for address, action, severity, ids in items:
        wants_pr = action in PR_ACTIONS
        # Critical drift always goes to a human; advise mode never opens PRs.
        delivery = (
            "pr" if wants_pr and severity != "critical" and config.mode == "open-prs" else "issue"
        )
        plans.append(
            RemediationPlan(
                key=f"{action}:{address}",
                address=address,
                action=action,
                delivery=delivery,
                severity=severity,
                finding_ids=ids,
            )
        )
    return sorted(plans, key=lambda p: -SEVERITY_RANK[p.severity])
