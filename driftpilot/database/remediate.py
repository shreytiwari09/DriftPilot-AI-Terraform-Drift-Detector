"""Pull-request patches for database drift: a new migration file, proven in a scratch database."""

import re
from dataclasses import dataclass
from pathlib import Path

from driftpilot.config import Config
from driftpilot.database.catalog import Catalog
from driftpilot.database.expected import read_migrations
from driftpilot.database.sql import migration_sql
from driftpilot.database.verify import verify_migration
from driftpilot.remediate.codify import Patch
from driftpilot.remediate.github_out import Item


def next_migration_name(existing: list[str], slug: str) -> str:
    """`<next number>_driftpilot_<slug>.sql`: the number goes one past the highest existing one."""
    numbers = [(int(m.group(1)), len(m.group(1))) for n in existing if (m := re.match(r"(\d+)", n))]
    number, width = max(numbers, default=(0, 4))
    clean = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")[:50] or "change"
    return f"{number + 1:0{width}d}_driftpilot_{clean}.sql"


@dataclass
class DatabaseContext:
    """What a database fix needs besides the findings: the live catalog and the scratch server."""

    working_dir: Path
    config: Config
    live: Catalog
    scratch_url: str | None
    baseline_ids: set[str]


def database_patch(item: Item, ctx: DatabaseContext) -> Patch | None:
    """A migration file for a `codify` plan, verified in a scratch database; None for other plans.

    Reverts and investigations get suggested SQL in the issue, not a patch.
    """
    if item.plan.action != "codify":
        return None
    if any(f.sensitive for f in item.findings):
        return Patch(False, {}, "", 0, "refused: a changed value is sensitive and was redacted")
    sql = migration_sql(item.findings)
    if sql is None:
        return Patch(False, {}, "", 0, "no automatic migration for this change: write it by hand")
    folder = ctx.working_dir / ctx.config.database.migrations
    existing = read_migrations(folder) if folder.is_dir() else []
    name = next_migration_name(
        [n for n, _ in existing], item.plan.address.removeprefix("postgres.")
    )
    files = {f"{ctx.config.database.migrations}/{name}": sql}
    if ctx.scratch_url is None:
        note = "not verified: no scratch database is configured to build the migrations in"
        return Patch(False, files, "", 0, note)
    result = verify_migration(
        ctx.live,
        existing,
        (name, sql),
        ctx.scratch_url,
        ctx.config.database.schemas,
        ctx.config.database.ignore,
        {f.address for f in item.findings},
        ctx.baseline_ids,
    )
    return Patch(result.verified, files, result.proof, 1, "database migration")
