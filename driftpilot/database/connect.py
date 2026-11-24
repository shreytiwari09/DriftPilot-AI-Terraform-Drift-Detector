"""Connections to Postgres. Passwords never reach a log, an error message or the screen."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

_URL_PASSWORD = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^:/?#\s@]*):[^@/?#\s]*@")
_KV_PASSWORD = re.compile(r"(?i)\b(password|passfile|sslpassword)\s*=\s*('[^']*'|\S+)")


class DatabaseError(RuntimeError):
    """A database problem, worded without the connection string."""


def redact_url(text: str) -> str:
    """Hide passwords in `postgresql://user:secret@host/db` URLs and `password=...` pairs."""
    return _KV_PASSWORD.sub(r"\1=***", _URL_PASSWORD.sub(r"\1:***@", text))


def _psycopg() -> Any:
    try:
        import psycopg
    except ImportError as e:
        raise DatabaseError("Postgres support needs psycopg: pip install 'driftpilot[db]'") from e
    return psycopg


@contextmanager
def connect(
    url: str, *, readonly: bool = True, autocommit: bool = False, dbname: str | None = None
) -> Iterator[Any]:
    """An open connection; `readonly` makes the whole session unable to write.

    `dbname` swaps the database of `url` (used for the scratch databases).
    """
    psycopg = _psycopg()
    extra: dict[str, Any] = {"dbname": dbname} if dbname else {}
    if readonly:
        extra["options"] = "-c default_transaction_read_only=on"
    try:
        conn = psycopg.connect(url, autocommit=autocommit, connect_timeout=15, **extra)
    except psycopg.Error as e:
        raise DatabaseError(f"could not connect to the database: {redact_url(str(e))}") from None
    except ValueError as e:  # a malformed URL
        raise DatabaseError(f"the database URL is not valid ({redact_url(str(e))[:80]})") from None
    try:
        if readonly:
            conn.read_only = True
        yield conn
    except psycopg.Error as e:
        raise DatabaseError(redact_url(str(e).strip())) from None
    finally:
        conn.close()


def url_from_env(env_name: str, environ: dict[str, str]) -> str:
    """The URL stored in an environment variable (only the variable's name is ever shown)."""
    value = environ.get(env_name, "").strip()
    if not value:
        raise DatabaseError(f"{env_name} is not set (it holds the database URL)")
    return value
