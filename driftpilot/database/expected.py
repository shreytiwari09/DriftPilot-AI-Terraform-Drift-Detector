"""The expected schema: what the migration files build, made in a scratch database.

DriftPilot creates `driftpilot_scratch_<random>` on the scratch server, runs the migrations in
file-name order, reads the catalog, and drops the database again (always, even on failure). It never
touches any other database.
"""

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from driftpilot.database.catalog import Catalog, catalog_from_connection
from driftpilot.database.connect import DatabaseError, connect, redact_url

SCRATCH_PREFIX = "driftpilot_scratch_"
_SCRATCH_NAME = re.compile(rf"^{SCRATCH_PREFIX}[a-z0-9_]{{4,40}}$")
_SKIP_SUFFIXES = (".down.sql", ".undo.sql", ".rollback.sql")


def scratch_name() -> str:
    return f"{SCRATCH_PREFIX}{uuid.uuid4().hex[:12]}"


def migration_files(directory: Path) -> list[Path]:
    """The `*.sql` files of a migrations folder in the order they are applied (by file name)."""
    if not directory.is_dir():
        raise DatabaseError(f"migrations folder not found: {directory}")
    files = sorted(p for p in directory.glob("*.sql") if not p.name.endswith(_SKIP_SUFFIXES))
    if not files:
        raise DatabaseError(f"no .sql migration files in {directory}")
    return files


def _check_scratch(name: str) -> str:
    """A safety belt: DriftPilot only ever creates or drops databases it names itself."""
    if not _SCRATCH_NAME.match(name):
        raise DatabaseError(f"refusing to touch database {name!r}: not a DriftPilot scratch name")
    return name


@contextmanager
def scratch_database(scratch_url: str) -> Iterator[str]:
    """Create a scratch database on the server `scratch_url` points to; drop it on exit.

    Yields the new database's name. The login in `scratch_url` needs CREATEDB.
    """
    from psycopg import sql

    name = _check_scratch(scratch_name())
    with connect(scratch_url, readonly=False, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield name
        finally:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(_check_scratch(name))
                )
            )


def apply_migrations(conn: Any, files: list[tuple[str, str]]) -> None:
    """Run each (name, SQL text) in order; the error says which file failed."""
    for name, text in files:
        try:
            conn.execute(text)
        except Exception as e:
            raise DatabaseError(
                f"migration {name} failed in the scratch database: {_first_line(e)}"
            ) from None


def _first_line(error: Exception) -> str:
    text = redact_url(str(error)).strip()
    return text.splitlines()[0] if text else type(error).__name__


def build_expected(
    scratch_url: str,
    files: list[tuple[str, str]],
    schemas: list[str],
    ignore: list[str] | None = None,
) -> Catalog:
    """The catalog the migrations build, read from a scratch database that is dropped afterwards."""
    with scratch_database(scratch_url) as name:
        with connect(scratch_url, readonly=False, autocommit=True, dbname=name) as conn:
            apply_migrations(conn, files)
        with connect(scratch_url, readonly=True, dbname=name) as conn:
            return catalog_from_connection(conn, schemas, ignore or [])


def read_migrations(directory: Path) -> list[tuple[str, str]]:
    return [(p.name, p.read_text()) for p in migration_files(directory)]
