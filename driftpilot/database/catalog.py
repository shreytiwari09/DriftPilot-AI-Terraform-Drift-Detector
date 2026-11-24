"""A normalized picture of a Postgres schema: tables, columns, constraints, indexes, RLS, grants.

`read_catalog` fills it from a live database with read-only queries. Everything is normalized so
two databases that are the same in meaning compare equal (type aliases, casts in defaults,
serial versus identity, auto-generated constraint and index names).
"""

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator

from driftpilot.database import BOOKKEEPING_TABLES
from driftpilot.database.connect import connect

_TYPE_ALIASES = {
    "int": "integer", "int4": "integer", "int2": "smallint", "int8": "bigint",
    "serial": "integer", "serial4": "integer", "bigserial": "bigint", "serial8": "bigint",
    "smallserial": "smallint", "serial2": "smallint",
    "varchar": "character varying", "bpchar": "character", "char": "character",
    "bool": "boolean", "float4": "real", "float8": "double precision", "decimal": "numeric",
    "timestamptz": "timestamp with time zone", "timestamp": "timestamp without time zone",
    "timetz": "time with time zone", "time": "time without time zone",
}  # fmt: skip
_TYPE_PARTS = re.compile(r"^([a-z0-9_. ]+?)\s*(\([^)]*\))?\s*((?:\[\s*\])*)$")
_CAST = re.compile(r"('(?:[^']|'')*')::[a-z_][a-z0-9_ ]*(?:\([^)]*\))?(?:\[\])?", re.I)
_NULL_CAST = re.compile(r"\bnull::[a-z_][a-z0-9_ ]*(?:\([^)]*\))?", re.I)
_NEXTVAL = re.compile(r"^nextval\(", re.I)
_INDEX_NAME = re.compile(r"^(CREATE (?:UNIQUE )?INDEX) \S+ ON ", re.I)


def normalize_type(text: str) -> str:
    """`int4` -> `integer`, `varchar(20)` -> `character varying(20)`, arrays keep their `[]`."""
    lowered = " ".join(text.lower().split())
    match = _TYPE_PARTS.match(lowered)
    if not match:
        return lowered
    base, params, brackets = match.groups()
    base = _TYPE_ALIASES.get(base, base)
    if base.startswith("public."):
        base = base.removeprefix("public.")
    return f"{base}{params or ''}{brackets.replace(' ', '')}"


def normalize_default(text: str | None) -> str | None:
    """A default expression without casts (`'x'::text` -> `'x'`) or outer parentheses."""
    if text is None:
        return None
    out = _CAST.sub(r"\1", _NULL_CAST.sub("NULL", text.strip()))
    while out.startswith("(") and out.endswith(")") and _balanced(out[1:-1]):
        out = out[1:-1].strip()
    out = out.replace("CURRENT_TIMESTAMP", "now()").replace("current_timestamp", "now()")
    return None if out.upper() == "NULL" or not out else out


def _balanced(text: str) -> bool:
    depth = 0
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if depth < 0:
            return False
    return depth == 0


def normalize_index(definition: str) -> str:
    """An index definition without its name: indexes are compared by what they index."""
    return _INDEX_NAME.sub(r"\1 ON ", " ".join(definition.split()))


def named_index(name: str, definition: str) -> str:
    """Put a name back into a normalized index definition."""
    return re.sub(r"^(CREATE (?:UNIQUE )?INDEX) ON ", rf"\1 {name} ON ", definition, count=1)


class Column(BaseModel):
    name: str
    type: str
    nullable: bool = True
    default: str | None = None  # not for serial/identity: those are `serial` / `identity`
    identity: Literal["always", "by default"] | None = None
    serial: bool = False  # default is nextval(...)
    generated: str | None = None  # expression of a stored generated column
    comment: str | None = None

    @field_validator("type")
    @classmethod
    def _type(cls, value: str) -> str:
        return normalize_type(value)

    @field_validator("default")
    @classmethod
    def _default(cls, value: str | None) -> str | None:
        return normalize_default(value)

    @model_validator(mode="after")
    def _serial(self) -> "Column":
        if self.default and _NEXTVAL.match(self.default):  # `serial`: a default from a sequence
            self.serial, self.default = True, None
        return self

    @property
    def auto(self) -> bool:
        """Fills itself in from a sequence: `serial` and `GENERATED ... AS IDENTITY` are alike."""
        return self.serial or self.identity is not None

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type, "nullable": self.nullable}
        for key in ("default", "generated"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        if self.identity:
            out["identity"] = self.identity
        if self.serial:
            out["serial"] = True
        return out


class Constraint(BaseModel):
    name: str  # only for display and SQL: constraints are compared by definition
    kind: Literal["primary key", "foreign key", "unique", "check", "exclusion"]
    definition: str  # e.g. `FOREIGN KEY (user_id) REFERENCES users(id)`

    @field_validator("definition")
    @classmethod
    def _definition(cls, value: str) -> str:
        return " ".join(value.split())

    @property
    def key(self) -> str:
        return self.definition


class Index(BaseModel):
    name: str  # only for display and SQL: indexes are compared by definition
    definition: str  # `CREATE [UNIQUE] INDEX ON schema.table USING btree (col)` (no name)

    @field_validator("definition")
    @classmethod
    def _definition(cls, value: str) -> str:
        return normalize_index(value)

    @property
    def key(self) -> str:
        return self.definition


class Policy(BaseModel):
    name: str
    command: str = "ALL"  # ALL | SELECT | INSERT | UPDATE | DELETE
    permissive: bool = True
    roles: list[str] = ["public"]
    using: str | None = None
    with_check: str | None = None

    @field_validator("roles")
    @classmethod
    def _roles(cls, value: list[str]) -> list[str]:
        return sorted({r.lower() for r in value})

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "command": self.command,
            "permissive": self.permissive,
            "roles": self.roles,
        }
        for key in ("using", "with_check"):
            if getattr(self, key) is not None:
                out[key] = getattr(self, key)
        return out


class Grant(BaseModel):
    grantee: str  # a role name, or PUBLIC
    privilege: str  # SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER

    @field_validator("grantee")
    @classmethod
    def _grantee(cls, value: str) -> str:
        return "PUBLIC" if value.upper() == "PUBLIC" else value

    @field_validator("privilege")
    @classmethod
    def _privilege(cls, value: str) -> str:
        return value.upper()

    @property
    def key(self) -> str:
        return f"{self.grantee}:{self.privilege}"


class Table(BaseModel):
    schema_name: str = "public"
    name: str
    columns: list[Column] = []
    constraints: list[Constraint] = []
    indexes: list[Index] = []
    rls_enabled: bool = False
    rls_forced: bool = False
    policies: list[Policy] = []
    grants: list[Grant] = []  # never the owner's own
    owner: str | None = None
    comment: str | None = None

    @property
    def qualified(self) -> str:
        return f"{self.schema_name}.{self.name}"

    def summary(self) -> dict[str, Any]:
        """What a whole table looks like, for a table that exists on one side only."""
        out: dict[str, Any] = {
            "columns": {c.name: c.summary() for c in self.columns},
            "constraints": [c.definition for c in self.constraints],
            "indexes": [i.definition for i in self.indexes],
        }
        if self.rls_enabled:
            out["row_level_security"] = True
        return out


class Catalog(BaseModel):
    tables: list[Table] = []

    def table(self, qualified: str) -> Table | None:
        return next((t for t in self.tables if t.qualified == qualified), None)

    def filtered(self, ignore: list[str]) -> "Catalog":
        """Without bookkeeping tables (`schema_migrations` ...) and the configured ignores."""
        skip = [*BOOKKEEPING_TABLES, *ignore]
        keep = [
            t
            for t in self.tables
            if not any(fnmatch(t.name, p) or fnmatch(t.qualified, p) for p in skip)
        ]
        return Catalog(tables=sorted(keep, key=lambda t: t.qualified))


def load_catalog(path: Path) -> Catalog:
    return Catalog.model_validate_json(path.read_text())


def save_catalog(catalog: Catalog, path: Path) -> None:
    path.write_text(catalog.model_dump_json(indent=2) + "\n")


# ---------- reading a live database (read-only queries only) ----------

_TABLES = """
SELECT c.oid, n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity,
       pg_get_userbyid(c.relowner), obj_description(c.oid, 'pg_class')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition AND n.nspname = ANY(%s)
"""
_COLUMNS = """
SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull,
       pg_get_expr(d.adbin, d.adrelid), a.attidentity, a.attgenerated,
       col_description(a.attrelid, a.attnum)
FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
WHERE a.attrelid = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attrelid, a.attnum
"""
_CONSTRAINTS = """
SELECT conrelid, conname, contype, pg_get_constraintdef(oid)
FROM pg_constraint WHERE conrelid = ANY(%s) AND contype IN ('p', 'f', 'u', 'c', 'x')
ORDER BY conrelid, conname
"""
_INDEXES = """
SELECT i.indrelid, ic.relname, pg_get_indexdef(i.indexrelid)
FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid
WHERE i.indrelid = ANY(%s) AND NOT EXISTS (
    SELECT 1 FROM pg_constraint k WHERE k.conindid = i.indexrelid AND k.contype IN ('p', 'u', 'x'))
ORDER BY i.indrelid, ic.relname
"""
_POLICIES = """
SELECT pol.polrelid, pol.polname, pol.polcmd, pol.polpermissive,
       ARRAY(SELECT CASE WHEN r = 0 THEN 'public' ELSE pg_get_userbyid(r) END
             FROM unnest(pol.polroles) AS r),
       pg_get_expr(pol.polqual, pol.polrelid), pg_get_expr(pol.polwithcheck, pol.polrelid)
FROM pg_policy pol WHERE pol.polrelid = ANY(%s) ORDER BY pol.polrelid, pol.polname
"""
_GRANTS = """
SELECT c.oid, CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
       a.privilege_type
FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
WHERE c.oid = ANY(%s) AND a.grantee <> c.relowner
ORDER BY c.oid, 2, 3
"""
_COMMANDS = {"*": "ALL", "r": "SELECT", "a": "INSERT", "w": "UPDATE", "d": "DELETE"}
_KINDS = {
    "p": "primary key", "f": "foreign key", "u": "unique", "c": "check", "x": "exclusion",
}  # fmt: skip


def _by(rows: list[tuple], index: int = 0) -> dict[int, list[tuple]]:
    out: dict[int, list[tuple]] = {}
    for row in rows:
        out.setdefault(row[index], []).append(row)
    return out


def catalog_from_connection(conn: Any, schemas: list[str], ignore: list[str]) -> Catalog:
    """Read a catalog through an open (read-only) connection."""
    tables = conn.execute(_TABLES, (schemas,)).fetchall()
    oids = [row[0] for row in tables]
    columns = _by(conn.execute(_COLUMNS, (oids,)).fetchall())
    constraints = _by(conn.execute(_CONSTRAINTS, (oids,)).fetchall())
    indexes = _by(conn.execute(_INDEXES, (oids,)).fetchall())
    policies = _by(conn.execute(_POLICIES, (oids,)).fetchall())
    grants = _by(conn.execute(_GRANTS, (oids,)).fetchall())
    out = []
    for oid, schema, name, rls, forced, owner, comment in tables:
        out.append(
            Table(
                schema_name=schema,
                name=name,
                columns=[_column(r) for r in columns.get(oid, [])],
                constraints=[
                    Constraint(name=r[1], kind=_KINDS[r[2]], definition=r[3])
                    for r in constraints.get(oid, [])
                ],
                indexes=[Index(name=r[1], definition=r[2]) for r in indexes.get(oid, [])],
                rls_enabled=rls,
                rls_forced=forced,
                policies=[
                    Policy(
                        name=r[1],
                        command=_COMMANDS.get(r[2], r[2]),
                        permissive=r[3],
                        roles=list(r[4]),
                        using=r[5],
                        with_check=r[6],
                    )  # fmt: skip
                    for r in policies.get(oid, [])
                ],
                grants=[Grant(grantee=r[1], privilege=r[2]) for r in grants.get(oid, [])],
                owner=owner,
                comment=comment,
            )
        )
    return Catalog(tables=out).filtered(ignore)


def _column(row: tuple) -> Column:
    _, name, type_, nullable, default, identity, generated, comment = row
    return Column(
        name=name,
        type=type_,
        nullable=nullable,
        default=None if generated == "s" else default,
        identity={"a": "always", "d": "by default"}.get(identity),
        generated=default if generated == "s" else None,
        comment=comment,
    )


def read_catalog(url: str, schemas: list[str], ignore: list[str] | None = None) -> Catalog:
    """The catalog of a live database. The session is read-only: nothing here can change it."""
    with connect(url, readonly=True) as conn:
        return catalog_from_connection(conn, schemas, ignore or [])
