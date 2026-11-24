"""Compare the schema the migrations build (expected) with the live one, as DriftFindings.

`before` is what the migrations say, `after` is what the live database has, like a Terraform
finding. An object only the live database has is `added`; one only the migrations have is `deleted`.
"""

from datetime import datetime
from typing import Any

from driftpilot.collector import finding_id
from driftpilot.database import PROVIDER
from driftpilot.database.catalog import Catalog, Column, Table
from driftpilot.models import DriftFinding

_COLUMN_ATTRS = ("type", "nullable", "default", "generated", "comment")


def table_address(t: Table) -> str:
    return f"{PROVIDER}.{t.schema_name}.{t.name}"


class _Diff:
    def __init__(self, run_id: str, detected_at: datetime) -> None:
        self.run_id, self.detected_at = run_id, detected_at
        self.findings: list[DriftFinding] = []

    def add(
        self, rtype: str, address: str, attr: str | None, before: Any, after: Any, kind: str
    ) -> None:
        self.findings.append(
            DriftFinding(
                id=finding_id(address, attr),
                run_id=self.run_id,
                detected_at=self.detected_at,
                provider=PROVIDER,
                resource_type=rtype,
                address=address,
                change_kind=kind,
                attribute_path=attr,
                before=before,
                after=after,
            )
        )

    def keyed(
        self,
        rtype: str,
        address: str,
        prefix: str,
        old: dict[str, Any],
        new: dict[str, Any],
        presence_only: bool = False,
    ) -> None:
        """Objects matched by key: only in `new` = added, only in `old` = deleted, else changed.

        `presence_only`: the key is the whole identity (a name does not count), so a key in both
        is the same object.
        """
        for key in sorted(set(old) | set(new)):
            if old.get(key) != new.get(key) and not (presence_only and key in old and key in new):
                self.add(
                    rtype, address, f"{prefix}:{key}", old.get(key), new.get(key),
                    _kind(old, new, key),
                )  # fmt: skip

    def table(self, e: Table, live: Table) -> None:
        address = table_address(e)
        for attr, old, new in (
            ("owner", e.owner, live.owner),
            ("comment", e.comment or None, live.comment or None),
        ):
            if old != new:
                self.add("pg_table", address, attr, old, new, "modified")
        for attr, old, new in (
            ("row_level_security", e.rls_enabled, live.rls_enabled),
            ("force_row_level_security", e.rls_forced, live.rls_forced),
        ):
            if old != new:
                self.add("pg_table_rls", address, attr, old, new, "modified")
        self.columns(address, e, live)
        self.keyed(
            "pg_constraint", address, "constraint",
            {c.key: {"name": c.name, "definition": c.definition} for c in e.constraints},
            {c.key: {"name": c.name, "definition": c.definition} for c in live.constraints},
            presence_only=True,
        )  # fmt: skip
        self.keyed(
            "pg_index", address, "index",
            {i.key: {"name": i.name, "definition": i.definition} for i in e.indexes},
            {i.key: {"name": i.name, "definition": i.definition} for i in live.indexes},
            presence_only=True,
        )  # fmt: skip
        self.policies_and_grants(address, e, live)

    def policies_and_grants(self, address: str, e: Table, live: Table) -> None:
        self.keyed(
            "pg_policy", address, "policy",
            {p.name: p.summary() for p in e.policies},
            {p.name: p.summary() for p in live.policies},
        )  # fmt: skip
        grant = lambda g: {"grantee": g.grantee, "privilege": g.privilege}  # noqa: E731
        self.keyed(
            "pg_grant", address, "grant",
            {g.key: grant(g) for g in e.grants}, {g.key: grant(g) for g in live.grants},
        )  # fmt: skip

    def columns(self, address: str, e: Table, live: Table) -> None:
        old, new = {c.name: c for c in e.columns}, {c.name: c for c in live.columns}
        for name in sorted(set(old) | set(new)):
            col_address = f"{address}.{name}"
            a, b = old.get(name), new.get(name)
            if a is None or b is None:
                kind = "deleted" if b is None else "added"
                self.add("pg_column", col_address, None, _col(a), _col(b), kind)
                continue
            for attr in _COLUMN_ATTRS:
                x, y = getattr(a, attr), getattr(b, attr)
                if attr == "comment":
                    x, y = x or None, y or None
                if x != y:
                    self.add("pg_column", col_address, attr, x, y, "modified")
            if _auto(a) != _auto(b):
                self.add("pg_column", col_address, "auto", _auto(a), _auto(b), "modified")


def _kind(old: dict[str, Any], new: dict[str, Any], key: str) -> str:
    return "added" if key not in old else "deleted" if key not in new else "modified"


def _col(c: Column | None) -> dict[str, Any] | None:
    return None if c is None else c.summary()


def _auto(c: Column) -> str | None:
    """How a column fills itself in. `serial` and `BY DEFAULT` identity behave alike."""
    if c.identity == "always":
        return "identity always"
    return "sequence" if c.auto else None


def diff_catalogs(
    expected: Catalog, live: Catalog, run_id: str, detected_at: datetime
) -> list[DriftFinding]:
    """Findings for every difference, in a stable order."""
    d = _Diff(run_id, detected_at)
    old = {t.qualified: t for t in expected.tables}
    new = {t.qualified: t for t in live.tables}
    for key in sorted(set(old) | set(new)):
        e, lv = old.get(key), new.get(key)
        if e is not None and lv is not None:
            d.table(e, lv)
            continue
        table = e or lv
        address = table_address(table)  # type: ignore[arg-type]
        kind = "deleted" if lv is None else "added"
        d.add(
            "pg_table",
            address,
            None,
            e.summary() if e else None,
            lv.summary() if lv else None,
            kind,
        )
        if lv is not None:  # a new table can still hold a policy or a grant to PUBLIC
            d.policies_and_grants(address, Table(name=lv.name, schema_name=lv.schema_name), lv)
    return d.findings
