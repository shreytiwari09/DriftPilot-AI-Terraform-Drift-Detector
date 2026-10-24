"""LLM triage for findings no rule decided (SPEC §4.4 step 2).

One LLM call per resource: the model sees all of a resource's changes together, which both judges
related changes better and keeps within free-tier request quotas.
"""

import json
import re
from functools import cache
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from driftpilot.hcl import find_block
from driftpilot.models import Action, Category, DriftFinding, Intent, Severity, Verdict
from driftpilot.triage.llm import LLMClient, LLMError, ask

_VERSION = re.compile(r"<!--\s*prompt_version:\s*(\S+)\s*-->")


class LLMVerdict(BaseModel):
    """A Verdict without finding_id/source, for one changed setting."""

    attribute_path: str | None
    is_real_drift: bool
    severity: Severity
    category: Category
    intent: Intent
    recommended_action: Action
    confidence: float = Field(ge=0, le=1)
    reason: str


class ResourceVerdicts(BaseModel):
    verdicts: list[LLMVerdict]


@cache
def load_prompt(name: str) -> tuple[str, str]:
    """(version, text) of `triage/prompts/<name>.md`; the version comes from its header comment."""
    text = resources.files("driftpilot.triage").joinpath(f"prompts/{name}.md").read_text()
    match = _VERSION.search(text)
    if not match:
        raise ValueError(f"prompt {name} has no prompt_version header")
    return match.group(1), _VERSION.sub("", text, count=1).strip()


def fallback_verdict(finding_id: str, why: str, prompt_version: str | None) -> Verdict:
    """Used when the LLM can't give a valid answer: a human must look."""
    return Verdict(
        finding_id=finding_id,
        source="llm",
        is_real_drift=True,
        severity="medium",
        category="security",
        intent="unknown",
        recommended_action="investigate",
        confidence=0.0,
        reason=f"Automatic triage was not possible ({why}); a person should review this change.",
        prompt_version=prompt_version,
    )


def build_input(
    findings: list[DriftFinding], working_dir: Path | None, history_counts: dict[str, int]
) -> dict:
    first = findings[0]
    block = find_block(working_dir, first.address) if working_dir else None
    return {
        "resource_type": first.resource_type,
        "address": first.address,
        "detected_at": first.detected_at.isoformat(),
        "resource_code": block.text if block else None,
        "changes": [
            {
                "attribute_path": f.attribute_path,
                "change_kind": f.change_kind,
                "before": f.before,
                "after": f.after,
                "times_drifted_before": history_counts.get(f.id, 0),
            }
            for f in findings
        ],
    }


def triage_resource(
    llm: LLMClient,
    findings: list[DriftFinding],
    working_dir: Path | None = None,
    history_counts: dict[str, int] | None = None,
) -> dict[str, Verdict]:
    """Verdicts for all `findings` of one resource; retry once on a bad answer; else investigate."""
    version, system = load_prompt("triage")
    payload = build_input(findings, working_dir, history_counts or {})
    prompt = "Judge these changes:\n" + json.dumps(payload, indent=2, default=str)
    by_path = {f.attribute_path: f for f in findings}
    out: dict[str, Verdict] = {}
    for attempt in range(2):
        try:
            raw = ask(llm, system, prompt, ResourceVerdicts.model_json_schema())
        except LLMError as e:
            reason = f"LLM unavailable: {str(e)[:120]}"
            return {f.id: fallback_verdict(f.id, reason, version) for f in findings}
        try:
            answers = ResourceVerdicts.model_validate_json(raw).verdicts
        except ValidationError as e:
            problem = f"it was not valid for the schema ({e.error_count()} error(s))"
        else:
            for a in answers:
                finding = by_path.get(a.attribute_path)
                if finding and finding.id not in out:
                    data = a.model_dump(exclude={"attribute_path"})
                    out[finding.id] = Verdict(
                        finding_id=finding.id, source="llm", prompt_version=version, **data
                    )
            missing = [f.attribute_path for f in findings if f.id not in out]
            if not missing:
                return out
            problem = f"it had no verdict for: {missing}"
        if attempt == 0:
            prompt += f"\n\nYour previous answer was rejected because {problem}. Answer again."
    for f in findings:
        out.setdefault(
            f.id, fallback_verdict(f.id, "the model's answer was invalid twice", version)
        )
    return out


def triage_findings(
    llm: LLMClient,
    findings: list[DriftFinding],
    decided: dict[str, Verdict],
    working_dir: Path | None = None,
    history_counts: dict[str, int] | None = None,
) -> dict[str, Verdict]:
    """Verdicts for every finding not already in `decided`, one LLM call per resource."""
    by_address: dict[str, list[DriftFinding]] = {}
    for f in findings:
        if f.id not in decided:
            by_address.setdefault(f.address, []).append(f)
    out: dict[str, Verdict] = {}
    for group in by_address.values():
        out |= triage_resource(llm, group, working_dir, history_counts)
    return out
