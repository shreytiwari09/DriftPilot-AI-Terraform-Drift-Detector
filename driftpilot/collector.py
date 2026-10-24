"""Run `terraform plan -refresh-only` and turn its JSON into DriftFindings (SPEC §4.1)."""

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from driftpilot.models import DriftFinding
from driftpilot.redact import is_marked_sensitive, redact

DEFAULT_TIMEOUT = 600  # seconds per terraform command


class TerraformError(RuntimeError):
    pass


def run_terraform(args: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TF_IN_AUTOMATION": "1", "TF_INPUT": "0"}
    try:
        return subprocess.run(
            ["terraform", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except FileNotFoundError as e:
        raise TerraformError("terraform not found on PATH") from e
    except subprocess.TimeoutExpired as e:
        raise TerraformError(f"terraform {args[0]} timed out after {timeout}s") from e


def check_result(
    result: subprocess.CompletedProcess[str], what: str, ok: tuple[int, ...] = (0,)
) -> None:
    if result.returncode not in ok:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise TerraformError(
            f"terraform {what} failed (exit {result.returncode}):\n{stderr[-4000:]}"
        )


def terraform_init(working_dir: Path, timeout: int = DEFAULT_TIMEOUT) -> None:
    check_result(run_terraform(["init", "-input=false", "-no-color"], working_dir, timeout), "init")


def refresh_only_plan(working_dir: Path, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Run a refresh-only plan and return `terraform show -json` of it.

    Exit codes with -detailed-exitcode: 0 = no drift, 2 = drift, 1 = error (confirmed in Phase 0).
    """
    with tempfile.TemporaryDirectory(prefix="driftpilot-") as tmp:
        plan_file = Path(tmp) / "drift.plan"
        args = [
            "plan", "-refresh-only", "-detailed-exitcode", "-input=false", "-lock=false",
            "-no-color", f"-out={plan_file}",
        ]  # fmt: skip
        check_result(run_terraform(args, working_dir, timeout), "plan", ok=(0, 2))
        shown = run_terraform(["show", "-json", str(plan_file)], working_dir, timeout)
        check_result(shown, "show")
    return json.loads(shown.stdout)


def show_state(working_dir: Path, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Current state as JSON (used by scanners to know what's managed)."""
    shown = run_terraform(["show", "-json"], working_dir, timeout)
    check_result(shown, "show")
    return json.loads(shown.stdout)


def managed_resource_count(plan: dict[str, Any]) -> int | None:
    """Managed resources in the plan's prior state (all modules), or None if absent."""
    root = (plan.get("prior_state") or {}).get("values", {}).get("root_module")
    if root is None:
        return None
    count, modules = 0, [root]
    while modules:
        module = modules.pop()
        count += sum(1 for r in module.get("resources", []) if r.get("mode") == "managed")
        modules.extend(module.get("child_modules", []))
    return count


def finding_id(address: str, attribute_path: str | None) -> str:
    return hashlib.sha256(f"{address}|{attribute_path or ''}".encode()).hexdigest()[:12]


def _child_marker(marker: Any, key: str | int) -> Any:
    if marker is True:
        return True
    if isinstance(marker, dict) and isinstance(key, str):
        return marker.get(key)
    if isinstance(marker, list) and isinstance(key, int) and key < len(marker):
        return marker[key]
    return None


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _diff(
    before: Any, after: Any, b_mark: Any, a_mark: Any, path: str = ""
) -> Iterator[tuple[str, Any, Any, Any, Any]]:
    """Yield (path, before, after, before_marker, after_marker) for each changed leaf.

    Lists of blocks with equal length are compared item by item (`ingress[0].cidr_blocks`).
    Lists of plain values (topics, tags, CIDRs), and lists whose length changed, are reported
    as one change of the whole list, so rules can see e.g. "same members, new order".
    """
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            yield from _diff(
                before.get(key), after.get(key),
                _child_marker(b_mark, key), _child_marker(a_mark, key), _join(path, key),
            )  # fmt: skip
    elif (
        isinstance(before, list)
        and isinstance(after, list)
        and len(before) == len(after)
        and any(isinstance(item, dict | list) for item in before + after)
    ):
        for i, (b, a) in enumerate(zip(before, after, strict=True)):
            yield from _diff(
                b, a, _child_marker(b_mark, i), _child_marker(a_mark, i), f"{path}[{i}]"
            )
    elif before != after:
        yield path, before, after, b_mark, a_mark


def resource_values(plan: dict[str, Any]) -> dict[str, Any]:
    """Redacted `after` value of each drifted resource, keyed by address.

    Rules use it as context, e.g. the port of the ingress block whose CIDR changed.
    """
    return {
        rc["address"]: redact(rc["change"].get("after"), rc["change"].get("after_sensitive"))
        for rc in plan.get("resource_drift") or []
    }


def parse_plan(plan: dict[str, Any], run_id: str, detected_at: datetime) -> list[DriftFinding]:
    """Turn `resource_drift[]` from plan JSON into findings, one per changed attribute."""
    findings: list[DriftFinding] = []
    for rc in plan.get("resource_drift") or []:
        change = rc["change"]
        actions = change.get("actions", [])
        common = {
            "run_id": run_id,
            "detected_at": detected_at,
            "provider": rc.get("provider_name", ""),
            "resource_type": rc["type"],
            "address": rc["address"],
        }
        if actions == ["delete"]:
            findings.append(
                DriftFinding(
                    id=finding_id(rc["address"], None),
                    change_kind="deleted",
                    attribute_path=None,
                    before=redact(change.get("before"), change.get("before_sensitive")),
                    after=None,
                    sensitive=is_marked_sensitive(change.get("before_sensitive")),
                    **common,
                )
            )
            continue
        for path, b, a, b_mark, a_mark in _diff(
            change.get("before"), change.get("after"),
            change.get("before_sensitive"), change.get("after_sensitive"),
        ):  # fmt: skip
            findings.append(
                DriftFinding(
                    id=finding_id(rc["address"], path or None),
                    change_kind="modified",
                    attribute_path=path or None,
                    before=redact(b, b_mark),
                    after=redact(a, a_mark),
                    sensitive=is_marked_sensitive(b_mark) or is_marked_sensitive(a_mark),
                    **common,
                )
            )
    return findings
