"""Policy: fixed rules that have the final say after rules and the LLM (SPEC §4.4 step 3)."""

from pydantic import BaseModel

from driftpilot.config import Config
from driftpilot.models import Action, DriftFinding, Severity, UnmanagedFinding, Verdict
from driftpilot.triage.rules import glob_match

SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}
PR_ACTIONS = {"codify", "ignore_changes", "import"}


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


def apply_policy(
    findings: list[DriftFinding],
    unmanaged: list[UnmanagedFinding],
    verdicts: dict[str, Verdict],
    config: Config,
) -> dict[str, Verdict]:
    """Return verdicts with config ignores, severity overrides and the confidence floor applied."""
    out = dict(verdicts)
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
        out.setdefault(u.id, unmanaged_verdict(u))
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
        items.append((f"{u.resource_kind}:{u.name}", "import", verdicts[u.id].severity, [u.id]))

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
