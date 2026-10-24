"""LLM triage for findings no rule decided (SPEC §4.4 step 2)."""

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
    """What the LLM must return: a Verdict without finding_id/source."""

    is_real_drift: bool
    severity: Severity
    category: Category
    intent: Intent
    recommended_action: Action
    confidence: float = Field(ge=0, le=1)
    reason: str


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
    finding: DriftFinding,
    siblings: list[DriftFinding],
    working_dir: Path | None,
    times_drifted_before: int,
) -> dict:
    block = find_block(working_dir, finding.address) if working_dir else None
    return {
        "resource_type": finding.resource_type,
        "address": finding.address,
        "change_kind": finding.change_kind,
        "attribute_path": finding.attribute_path,
        "before": finding.before,
        "after": finding.after,
        "detected_at": finding.detected_at.isoformat(),
        "times_drifted_before": times_drifted_before,
        "other_changes_on_resource": [
            {"attribute_path": s.attribute_path, "before": s.before, "after": s.after}
            for s in siblings
        ],
        "resource_code": block.text if block else None,
    }


def triage_one(
    llm: LLMClient,
    finding: DriftFinding,
    siblings: list[DriftFinding],
    working_dir: Path | None = None,
    times_drifted_before: int = 0,
) -> Verdict:
    """Ask the LLM; parse into a Verdict; retry once on a bad answer; else `investigate`."""
    version, system = load_prompt("triage")
    payload = build_input(finding, siblings, working_dir, times_drifted_before)
    prompt = "Judge this change:\n" + json.dumps(payload, indent=2, default=str)
    schema = LLMVerdict.model_json_schema()
    for attempt in range(2):
        try:
            raw = ask(llm, system, prompt, schema)
        except LLMError as e:
            return fallback_verdict(finding.id, f"LLM unavailable: {str(e)[:120]}", version)
        try:
            parsed = LLMVerdict.model_validate_json(raw)
        except ValidationError as e:
            if attempt == 0:
                prompt += (
                    "\n\nYour previous answer was not valid for the schema "
                    f"({e.error_count()} error(s)). Answer again with valid JSON only."
                )
                continue
            return fallback_verdict(finding.id, "the model's answer was invalid twice", version)
        return Verdict(
            finding_id=finding.id, source="llm", prompt_version=version, **parsed.model_dump()
        )
    raise AssertionError("unreachable")


def triage_findings(
    llm: LLMClient,
    findings: list[DriftFinding],
    decided: dict[str, Verdict],
    working_dir: Path | None = None,
    history_counts: dict[str, int] | None = None,
) -> dict[str, Verdict]:
    """Verdicts for every finding not already in `decided`."""
    history_counts = history_counts or {}
    out: dict[str, Verdict] = {}
    for finding in findings:
        if finding.id in decided:
            continue
        siblings = [f for f in findings if f.address == finding.address and f.id != finding.id]
        out[finding.id] = triage_one(
            llm, finding, siblings, working_dir, history_counts.get(finding.id, 0)
        )
    return out
