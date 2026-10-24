"""Import an unmanaged resource: import block → generated config → LLM tidy → verify (SPEC §4.5)."""

import json
import re
import tempfile
from pathlib import Path

from pydantic import ValidationError

from driftpilot.collector import DEFAULT_TIMEOUT, run_terraform
from driftpilot.hcl import find_block
from driftpilot.remediate.codify import CodifyAnswer, Patch
from driftpilot.remediate.verify import copy_workdir, verify_patch
from driftpilot.scanners.base import ImportTarget
from driftpilot.triage.llm import LLMClient, LLMError, ask
from driftpilot.triage.llm_triage import load_prompt


def import_block(target: ImportTarget) -> str:
    return f'import {{\n  to = {target.address}\n  id = "{target.import_id}"\n}}\n'


def generate_config(
    working_dir: Path, target: ImportTarget, timeout: int = DEFAULT_TIMEOUT
) -> tuple[str | None, str]:
    """Let Terraform write the resource block for `target`. Returns (block or None, log)."""
    with tempfile.TemporaryDirectory(prefix="driftpilot-import-") as tmp:
        work = Path(tmp) / "work"
        copy_workdir(working_dir, work)
        (work / "driftpilot_import.tf").write_text(import_block(target))
        args = [
            "plan",
            "-input=false",
            "-lock=false",
            "-no-color",
            "-generate-config-out=generated.tf",
        ]
        result = run_terraform([*args, f"-target={target.address}"], work, timeout)
        generated = work / "generated.tf"
        if not generated.exists():
            return None, (result.stderr or result.stdout).strip()
        text = generated.read_text()
    match = re.search(r'resource\s+"[^"]+"\s+"[^"]+"\s*\{', text)
    return (text[match.start() :].strip() if match else None), ""


def _style_example(working_dir: Path, target: ImportTarget) -> str | None:
    """An existing block of the same type, if the repo has one, so the LLM can match its style."""
    for path in sorted(working_dir.glob("*.tf")):
        for name in re.findall(
            rf'resource\s+"{re.escape(target.tf_type)}"\s+"([^"]+)"', path.read_text()
        ):
            block = find_block(working_dir, f"{target.tf_type}.{name}")
            if block:
                return block.text
    return None


def import_resource(
    llm: LLMClient | None, working_dir: Path, target: ImportTarget, max_retries: int = 3
) -> Patch:
    """A verified patch file `imported_<name>.tf` holding the import block and resource code."""
    generated, log = generate_config(working_dir, target)
    if generated is None:
        return Patch(False, {}, log[-3000:], 0, "terraform could not generate config")

    rel = f"imported_{target.name}.tf"

    def attempt(block: str):
        files = {rel: import_block(target) + "\n" + block.strip() + "\n"}
        return verify_patch(working_dir, files, expect="import_only", targets=[target.address])

    if llm is not None:
        version, system = load_prompt("import")
        request = {
            "generated_block": generated,
            "style_example": _style_example(working_dir, target),
        }
        prompt = "Tidy this block:\n" + json.dumps(request, indent=2)
        for n in range(1, max_retries + 1):
            try:
                raw = ask(llm, system, prompt, CodifyAnswer.model_json_schema())
                block = CodifyAnswer.model_validate_json(raw).block
            except (LLMError, ValidationError):
                continue
            result = attempt(block)
            if result.verified:
                return Patch(True, result.files, result.output, n, version)
            prompt += (
                f"\n\nAttempt {n} was not accepted: terraform {result.stage} said:\n"
                f"{result.output[-3000:]}\nReturn a corrected block."
            )
    # Last resort: Terraform's own generated code — verbose, but written from the real resource.
    result = attempt(generated)
    return Patch(result.verified, result.files, result.output, max_retries + 1, "generated config")
