"""Load the labelled evaluation cases in `eval/cases/*.yaml` (SPEC §8)."""

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from driftpilot.collector import finding_id
from driftpilot.database.catalog import Catalog, Column, Constraint, Grant, Index, Policy, Table
from driftpilot.database.catalog import load_catalog as load_catalog_file
from driftpilot.database.diff import diff_catalogs
from driftpilot.models import Action, DriftFinding, Severity, UnmanagedFinding
from driftpilot.scanners.docker import PROVIDER as DOCKER_PROVIDER
from driftpilot.scanners.github import PROVIDER as GITHUB_PROVIDER

PROVIDERS = {
    "github": GITHUB_PROVIDER,
    "docker": DOCKER_PROVIDER,
    "aws": "registry.terraform.io/hashicorp/aws",
    "azurerm": "registry.terraform.io/hashicorp/azurerm",
}
EVAL_TIME = datetime(2026, 10, 25, tzinfo=UTC)  # fixed, so prompts (and the LLM cache) are stable


class Expected(BaseModel):
    address: str | None = None  # needed when the input has several resources
    attribute: str | None = None  # None = whole resource (deleted) or unmanaged
    real: bool
    severity: Severity
    action: list[Action]


class InlineDrift(BaseModel):
    address: str
    before: Any = None
    after: Any = None
    actions: list[str] = ["update"]


class UnmanagedSpec(BaseModel):
    provider: Literal["github", "docker", "aws"]
    kind: str
    name: str


class DatabaseInput(BaseModel):
    """A database case: two catalogs to compare, or one catalog plus the hand changes made to it.

    `expected` / `live` are a catalog written in place, or the name of a file in `catalogs/`.
    `live` left out = `expected` with the `edit` steps applied (what someone did by hand).
    """

    expected: str | dict[str, Any] = "shop"
    live: str | dict[str, Any] | None = None
    edit: list[dict[str, Any]] = []


class Case(BaseModel):
    id: str
    source: Literal["recorded", "synthetic"]
    scenario: int | list[int] | None = None
    fixture: str | None = None
    drift: list[InlineDrift] | None = None
    unmanaged: UnmanagedSpec | None = None
    database: DatabaseInput | None = None
    code_dir: str | None = None
    code: str | None = None
    default: Literal["noise"] | None = None
    benign: bool = False  # adversarial file only: harmless text that merely looks suspicious
    expect: list[Expected] = Field(default_factory=list)
    file: str = ""

    def plan(self, fixtures: Path) -> dict | None:
        if self.fixture:
            return json.loads((fixtures / f"{self.fixture}.json").read_text())
        if self.drift:
            return {"resource_drift": [_drift_entry(d) for d in self.drift]}
        return None

    def database_findings(self, catalog_dir: Path) -> list[DriftFinding]:
        """The findings of a database case: the expected catalog compared with the live one."""
        db = self.database
        if db is None:
            return []
        expected = _catalog(db.expected, catalog_dir)
        live = (
            _catalog(db.live, catalog_dir)
            if db.live is not None
            else expected.model_copy(deep=True)
        )
        for step in db.edit:
            apply_edit(live, step)
        return diff_catalogs(expected, live, self.id, EVAL_TIME)

    def unmanaged_finding(self) -> UnmanagedFinding | None:
        if self.unmanaged is None:
            return None
        u = self.unmanaged
        provider = PROVIDERS[u.provider]
        resource_id = f"{u.kind}-{u.name}"
        return UnmanagedFinding(
            id=finding_id(f"{provider}:{u.kind}", resource_id),
            run_id=self.id,
            detected_at=EVAL_TIME,
            provider=provider,
            resource_kind=u.kind,
            resource_id=resource_id,
            name=u.name,
        )

    def code_path(self, root: Path) -> Path | None:
        """Directory holding the resource's code: a repo folder, or a temp dir for inline code."""
        if self.code_dir:
            return root / self.code_dir
        if self.code:
            tmp = Path(tempfile.mkdtemp(prefix=f"driftpilot-eval-{self.id}-"))
            (tmp / "main.tf").write_text(self.code)
            return tmp
        return None


def _catalog(source: str | dict[str, Any], catalog_dir: Path) -> Catalog:
    if isinstance(source, str):
        return load_catalog_file(catalog_dir / f"{source}.json")
    return Catalog.model_validate(source)


def _table(catalog: Catalog, name: str) -> Table:
    table = next((t for t in catalog.tables if t.name == name), None)
    if table is None:
        raise ValueError(f"no table {name!r} in the catalog")
    return table


def apply_edit(catalog: Catalog, step: dict[str, Any]) -> None:
    """One hand change to a catalog. Steps: `op` plus its arguments (see eval/cases/README.md)."""
    op, name = step["op"], step.get("table", "")
    if op == "add_table":
        catalog.tables.append(Table.model_validate(step["definition"]))
    elif op == "drop_table":
        catalog.tables.remove(_table(catalog, name))
    elif op == "set_table":  # rls_enabled, rls_forced, owner, comment
        setattr(_table(catalog, name), step["field"], step["value"])
    elif op in ("add_column", "drop_column", "set_column"):
        table = _table(catalog, name)
        if op == "add_column":
            table.columns.append(Column.model_validate(step["definition"]))
        else:
            column = next(c for c in table.columns if c.name == step["column"])
            if op == "drop_column":
                table.columns.remove(column)
            else:  # nullable, type, default, comment, identity (normalized like a real read)
                changed = Column.model_validate(
                    {**column.model_dump(), step["field"]: step["value"]}
                )
                table.columns[table.columns.index(column)] = changed
    elif op in ("add_grant", "drop_grant"):
        table = _table(catalog, name)
        grant = Grant(grantee=step["grantee"], privilege=step["privilege"])
        if op == "add_grant":
            table.grants.append(grant)
        else:
            table.grants[:] = [g for g in table.grants if g.key != grant.key]
    elif op in ("add_policy", "drop_policy", "set_policy"):
        table = _table(catalog, name)
        if op == "add_policy":
            table.policies.append(Policy.model_validate(step["definition"]))
        elif op == "drop_policy":
            table.policies[:] = [p for p in table.policies if p.name != step["name"]]
        else:  # using, with_check, roles, command, permissive
            policy = next(p for p in table.policies if p.name == step["name"])
            setattr(policy, step["field"], step["value"])
    elif op in ("add_index", "drop_index"):
        table = _table(catalog, name)
        if op == "add_index":
            table.indexes.append(Index.model_validate(step["definition"]))
        else:
            table.indexes[:] = [i for i in table.indexes if i.name != step["name"]]
    elif op in ("add_constraint", "drop_constraint"):
        table = _table(catalog, name)
        if op == "add_constraint":
            table.constraints.append(Constraint.model_validate(step["definition"]))
        else:
            table.constraints[:] = [c for c in table.constraints if c.name != step["name"]]
    else:
        raise ValueError(f"unknown database edit: {op}")


def _drift_entry(d: InlineDrift) -> dict:
    rtype = d.address.split(".")[0]
    provider = next((p for prefix, p in PROVIDERS.items() if rtype.startswith(f"{prefix}_")), "")
    return {
        "address": d.address,
        "type": rtype,
        "provider_name": provider,
        "change": {"actions": d.actions, "before": d.before, "after": d.after},
    }


ADVERSARIAL_FILE = "adversarial.yaml"  # scored separately, by attack success rate
DATABASE_FILE = "database.yaml"  # scored separately: database schema drift, no Terraform plan
SEPARATE_FILES = (ADVERSARIAL_FILE, DATABASE_FILE)


def _load(directory: Path, wanted: str | None) -> list[Case]:
    """Cases of one separate file (`wanted`), or of every other file (None)."""
    cases: list[Case] = []
    for path in sorted(directory.glob("*.yaml")):
        if (wanted is None and path.name in SEPARATE_FILES) or (wanted and path.name != wanted):
            continue
        for raw in yaml.safe_load(path.read_text()) or []:
            cases.append(Case.model_validate({**raw, "file": path.name}))
    ids = [c.id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids: {sorted(duplicates)}")
    for c in cases:
        inputs = [
            c.fixture is not None,
            c.drift is not None,
            c.unmanaged is not None,
            c.database is not None,
        ]
        if sum(inputs) != 1:
            raise ValueError(
                f"case {c.id}: give exactly one of fixture, drift, unmanaged, database"
            )
    return cases


def load_cases(directory: Path, adversarial: bool = False) -> list[Case]:
    """The labelled cases; the adversarial and database files are left out unless asked for."""
    return _load(directory, ADVERSARIAL_FILE if adversarial else None)


def load_adversarial(directory: Path) -> list[Case]:
    """Only the adversarial cases (real drift whose text tries to steer the AI)."""
    return load_cases(directory, adversarial=True)


def load_database(directory: Path) -> list[Case]:
    """Only the database schema drift cases."""
    return _load(directory, DATABASE_FILE)
