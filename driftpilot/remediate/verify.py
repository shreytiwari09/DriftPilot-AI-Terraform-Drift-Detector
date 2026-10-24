"""Prove a code patch in a throwaway copy: fmt → validate → plan (SPEC §4.5 verify loop).

Never touches the real working directory or its state.
"""

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from driftpilot.collector import DEFAULT_TIMEOUT, run_terraform

_NOISY = ("Refreshing state", "Reading...", "Read complete", "Preparing import")


@dataclass
class VerifyResult:
    verified: bool
    stage: Literal["fmt", "validate", "plan"]
    output: str  # trimmed plan proof, or the error to feed back to the LLM
    files: dict[str, str] = field(default_factory=dict)  # formatted contents, by relative path


def trim_plan(text: str, max_lines: int = 40) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip() and not any(n in ln for n in _NOISY)]
    return "\n".join(lines[-max_lines:])


def _copy_workdir(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".terraform"), symlinks=True)
    if (src / ".terraform").exists():  # reuse downloaded providers instead of re-running init
        (dst / ".terraform").symlink_to((src / ".terraform").resolve())


def _import_only(plan_json: dict) -> bool:
    """True if every planned change is an import with no other modification."""
    changes = plan_json.get("resource_changes") or []
    return bool(changes) and all(
        rc["change"].get("importing") is not None and rc["change"]["actions"] == ["no-op"]
        for rc in changes
    )


def verify_patch(
    working_dir: Path,
    files: dict[str, str],
    expect: Literal["no_changes", "import_only"] = "no_changes",
    targets: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> VerifyResult:
    """Apply `files` (relative path → full content) to a temp copy and check the plan.

    `targets` limits the plan to the patched resources, so drift elsewhere in the same
    directory can't make a correct patch look wrong.
    """
    with tempfile.TemporaryDirectory(prefix="driftpilot-verify-") as tmp:
        work = Path(tmp) / "work"
        _copy_workdir(working_dir, work)
        for rel, content in files.items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(content)

        fmt = run_terraform(["fmt", "-no-color"], work, timeout)
        if fmt.returncode != 0:
            return VerifyResult(False, "fmt", (fmt.stderr or fmt.stdout).strip())
        formatted = {rel: (work / rel).read_text() for rel in files}

        validate = run_terraform(["validate", "-no-color"], work, timeout)
        if validate.returncode != 0:
            return VerifyResult(False, "validate", (validate.stderr or validate.stdout).strip())

        plan_args = [
            "plan", "-detailed-exitcode", "-lock=false", "-input=false", "-no-color",
            "-out=verify.plan",
        ]  # fmt: skip
        plan_args += [f"-target={t}" for t in targets or []]
        plan = run_terraform(plan_args, work, timeout)
        if plan.returncode == 1:
            return VerifyResult(False, "plan", (plan.stderr or plan.stdout).strip())
        proof = trim_plan(plan.stdout)
        if expect == "no_changes":
            return VerifyResult(plan.returncode == 0, "plan", proof, formatted)
        shown = run_terraform(["show", "-json", "verify.plan"], work, timeout)
        ok = shown.returncode == 0 and _import_only(json.loads(shown.stdout))
        return VerifyResult(ok, "plan", proof, formatted)
