"""Codify and ignore_changes patches, each proven by `verify.py` (SPEC §4.5)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ValidationError

from driftpilot.hcl import add_ignore_changes, find_block, replace_block
from driftpilot.models import DriftFinding
from driftpilot.remediate.verify import verify_patch
from driftpilot.triage.llm import LLMClient, LLMError, ask
from driftpilot.triage.llm_triage import load_prompt


@dataclass
class Patch:
    verified: bool
    files: dict[str, str]  # relative path → full new content (formatted when it got that far)
    proof: str  # trimmed plan output, or the last error
    attempts: int
    note: str = ""


class CodifyAnswer(BaseModel):
    block: str


def _relative(block_path: Path, working_dir: Path) -> str:
    return str(block_path.relative_to(working_dir))


def codify(
    llm: LLMClient, working_dir: Path, findings: list[DriftFinding], max_retries: int = 3
) -> Patch:
    """Ask the LLM to rewrite the resource block to match reality; verify; feed errors back."""
    address = findings[0].address
    if any(f.sensitive for f in findings):
        return Patch(False, {}, "", 0, "refused: a changed value is sensitive and was redacted")
    if any(f.change_kind == "deleted" for f in findings):
        return Patch(False, {}, "", 0, "refused: the resource was deleted; recreate it instead")
    block = find_block(working_dir, address)
    if block is None:
        return Patch(False, {}, "", 0, f"no resource block found for {address}")

    version, system = load_prompt("codify")
    request = {
        "resource_block": block.text,
        "settings": [
            {"path": f.attribute_path, "code_value": f.before, "real_value": f.after}
            for f in findings
        ],
    }
    prompt = "Update this block:\n" + json.dumps(request, indent=2, default=str)
    rel = _relative(block.path, working_dir)
    last = Patch(False, {}, "", 0, "")
    for attempt in range(1, max_retries + 1):
        try:
            raw = ask(llm, system, prompt, CodifyAnswer.model_json_schema())
            new_block = CodifyAnswer.model_validate_json(raw).block
        except (LLMError, ValidationError) as e:
            last = Patch(False, {}, str(e)[:500], attempt, f"{version}: no usable answer")
            continue
        if not re.match(rf'\s*resource\s+"{re.escape(findings[0].resource_type)}"', new_block):
            feedback = "The answer must be the complete resource block, starting with `resource`."
            last = Patch(False, {}, feedback, attempt, f"{version}: wrong shape")
        else:
            files = {rel: replace_block(block, new_block)}
            result = verify_patch(working_dir, files, targets=[address])
            if result.verified:
                return Patch(True, result.files or files, result.output, attempt, version)
            feedback = f"terraform {result.stage} failed:\n{result.output[-3000:]}"
            last = Patch(False, result.files or files, result.output, attempt, version)
        prompt += f"\n\nAttempt {attempt} was not accepted. {feedback}\nReturn a corrected block."
    return last


def ignore_changes(working_dir: Path, findings: list[DriftFinding]) -> Patch:
    """Add the drifted top-level attributes to `lifecycle.ignore_changes`; verify."""
    block = find_block(working_dir, findings[0].address)
    if block is None:
        return Patch(False, {}, "", 0, f"no resource block found for {findings[0].address}")
    text = block.text
    for f in findings:
        if f.attribute_path:  # ignore the whole top-level attribute or nested block
            text = add_ignore_changes(text, re.split(r"[.\[]", f.attribute_path, maxsplit=1)[0])
    files = {_relative(block.path, working_dir): replace_block(block, text)}
    result = verify_patch(working_dir, files, targets=[findings[0].address])
    return Patch(result.verified, result.files or files, result.output, 1, "ignore_changes")
