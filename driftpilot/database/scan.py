"""Getting the two catalogs of a database scan: from live databases, or replayed from JSON."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from driftpilot.config import Config
from driftpilot.database.catalog import Catalog, load_catalog, read_catalog
from driftpilot.database.connect import url_from_env
from driftpilot.database.expected import build_expected, read_migrations


@dataclass
class Catalogs:
    expected: Catalog  # what the migration files build
    live: Catalog  # what the live database has


def scratch_url(config: Config, environ: Mapping[str, str] | None = None) -> str | None:
    """The scratch server's URL from the environment, or None when it is not set."""
    value = (environ if environ is not None else os.environ).get(config.database.scratch_url_env)
    return value.strip() or None if value else None


def load_catalogs(
    working_dir: Path,
    config: Config,
    expected_json: Path | None = None,
    live_json: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Catalogs:
    """Read both catalogs. A JSON file replaces the matching database (replay, tests, offline)."""
    env = environ if environ is not None else os.environ
    db, ignore = config.database, config.database.ignore
    if live_json is not None:
        live = load_catalog(live_json)
    else:
        live = read_catalog(url_from_env(db.url_env, dict(env)), db.schemas, ignore)
    if expected_json is not None:
        expected = load_catalog(expected_json)
    else:
        scratch = url_from_env(db.scratch_url_env, dict(env))
        files = read_migrations(working_dir / db.migrations)
        expected = build_expected(scratch, files, db.schemas, ignore)
    return Catalogs(expected=expected, live=live)
