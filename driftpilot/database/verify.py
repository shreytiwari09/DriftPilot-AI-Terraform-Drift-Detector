"""Prove a migration: build the schema from all migrations plus the new file, compare with live.

The database version of Terraform's "No changes": if the schema the migrations now build equals
the live database on the objects the patch is about, the migration describes reality.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from driftpilot.database.catalog import Catalog
from driftpilot.database.connect import DatabaseError
from driftpilot.database.diff import diff_catalogs
from driftpilot.database.expected import build_expected
from driftpilot.models import DriftFinding
from driftpilot.triage.rules import apply_rules, load_rules

PROOF_START = "Schema built from migrations matches the live database"
PROOF = f"{PROOF_START} (0 differences)"


@dataclass
class DbVerifyResult:
    verified: bool
    proof: str  # the proof text, or why it failed


def real_differences(findings: list[DriftFinding]) -> list[DriftFinding]:
    """Differences a person cares about: those the rules do not call noise (owner, comments)."""
    noise = {
        fid for fid, v in apply_rules(findings, load_rules(), {}).items() if not v.is_real_drift
    }
    return [f for f in findings if f.id not in noise]


def verify_migration(
    live: Catalog,
    migrations: list[tuple[str, str]],
    new_file: tuple[str, str],
    scratch_url: str,
    schemas: list[str],
    ignore: list[str],
    addresses: set[str],
    baseline_ids: set[str],
) -> DbVerifyResult:
    """Build from `migrations` + `new_file` in a fresh scratch database and diff against `live`.

    Verified when no difference is left on the `addresses` the patch is about and the migration
    created no difference that was not already there (`baseline_ids`).
    """
    try:
        expected = build_expected(scratch_url, [*migrations, new_file], schemas, ignore)
    except DatabaseError as e:
        return DbVerifyResult(False, str(e))
    left = real_differences(diff_catalogs(expected, live, "verify", datetime.now(UTC)))
    affected = [f for f in left if f.address in addresses]
    created = [f for f in left if f.id not in baseline_ids]
    if affected or created:
        shown = ", ".join(
            f"{f.address} {f.attribute_path or ''}".strip() for f in affected + created
        )
        return DbVerifyResult(False, f"Still different after adding the migration: {shown}")
    if not left:
        return DbVerifyResult(True, PROOF)
    return DbVerifyResult(
        True,
        f"{PROOF_START} (0 differences on the affected objects; "
        f"{len(left)} other difference(s) remain)",
    )
