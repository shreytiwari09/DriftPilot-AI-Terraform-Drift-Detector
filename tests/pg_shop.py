"""Catalog helpers for the Postgres tests: the demo's schema, and small edits to it."""

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from driftpilot.database.catalog import Catalog, Table, load_catalog
from driftpilot.database.diff import diff_catalogs
from driftpilot.models import DriftFinding

FIXTURES = Path(__file__).parent / "fixtures" / "postgres"
NOW = datetime(2026, 11, 24, tzinfo=UTC)


def shop() -> Catalog:
    """What the demo's three migrations build (users and orders)."""
    return load_catalog(FIXTURES / "shop_expected.json")


def edit(catalog: Catalog, table: str, change: Callable[[Table], None]) -> Catalog:
    """A copy of `catalog` where `change` was applied to table `table` (a deep copy)."""
    copy = catalog.model_copy(deep=True)
    change(next(t for t in copy.tables if t.name == table))
    return copy


def findings(expected: Catalog, live: Catalog) -> list[DriftFinding]:
    return diff_catalogs(expected, live, "run", NOW)


def by_attr(items: list[DriftFinding]) -> dict[tuple[str, str | None], DriftFinding]:
    return {(f.address, f.attribute_path): f for f in items}
