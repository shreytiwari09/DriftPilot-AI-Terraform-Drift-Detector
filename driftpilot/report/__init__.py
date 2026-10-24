"""Shared helpers for presenting scan results."""

import json
from typing import Any

from driftpilot.models import DriftFinding, ScanResult, Verdict

# Display order; "triage" = no rule decided yet.
SEVERITY_ORDER = ["critical", "high", "medium", "low", "triage", "none"]


def severity_of(verdict: Verdict | None) -> str:
    return verdict.severity if verdict else "triage"


def sorted_findings(result: ScanResult, show_noise: bool = False) -> list[DriftFinding]:
    findings = result.findings if show_noise else result.real_findings
    return sorted(
        findings,
        key=lambda f: (
            SEVERITY_ORDER.index(severity_of(result.verdicts.get(f.id))),
            f.address,
            f.attribute_path or "",
        ),
    )


def counts(result: ScanResult) -> dict[str, int]:
    out = dict.fromkeys(SEVERITY_ORDER, 0)
    for f in result.real_findings:
        out[severity_of(result.verdicts.get(f.id))] += 1
    out["noise"] = len(result.findings) - len(result.real_findings)
    out["unmanaged"] = len(result.unmanaged)
    return out


def short(value: Any, limit: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def change_text(f: DriftFinding) -> str:
    if f.change_kind == "deleted":
        return "deleted outside Terraform"
    return f"{short(f.before)} → {short(f.after)}"


def decided_by(v: Verdict | None) -> str:
    """Who made the call, e.g. "rule github-team-permission-admin" or "AI (triage-v2), 90%"."""
    if v is None:
        return "no rule matched; no LLM configured"
    if v.source == "rule":
        return f"rule {v.rule_id}"
    if v.source == "llm":
        return f"AI ({v.prompt_version}), {v.intent}, {v.confidence:.0%}"
    return "policy"
