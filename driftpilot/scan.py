"""One drift scan: plan -> findings -> rules, plus unmanaged-resource scanners."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from driftpilot.collector import (
    parse_plan,
    refresh_only_plan,
    resource_values,
    show_state,
    terraform_init,
)
from driftpilot.config import Config
from driftpilot.models import ScanResult
from driftpilot.scanners import build_scanners
from driftpilot.scanners.base import find_unmanaged
from driftpilot.triage.rules import apply_rules, load_rules


def run_scan(
    working_dir: Path,
    config: Config,
    plan_json: Path | None = None,
    state_json: Path | None = None,
) -> ScanResult:
    """Run a scan. `plan_json` / `state_json` replay recorded files instead of calling Terraform."""
    now = datetime.now(UTC)
    result = ScanResult(
        run_id=f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}",
        started_at=now,
        working_dir=str(working_dir),
    )

    if plan_json is None:
        terraform_init(working_dir)
        plan = refresh_only_plan(working_dir)
    else:
        plan = json.loads(plan_json.read_text())
    result.findings = parse_plan(plan, result.run_id, now)
    result.verdicts = apply_rules(result.findings, load_rules(), resource_values(plan))

    # Scanners need state; in replay mode they only run if a recorded state is given.
    if plan_json is not None and state_json is None:
        return result
    try:
        scanners = build_scanners(config)
    except Exception as e:  # e.g. missing token: report it, keep the drift results
        result.errors.append(f"scanners: {e}")
        return result
    if not scanners:
        return result
    state = json.loads(state_json.read_text()) if state_json else show_state(working_dir)
    for scanner in scanners:
        try:
            result.unmanaged += find_unmanaged(scanner, state, result.run_id, now)
        except Exception as e:  # one platform failing shouldn't hide the others
            result.errors.append(f"{type(scanner).__name__}: {e}")
    return result
