"""Postgres schema drift: what the migration files say against what the live database has."""

PROVIDER = "postgres"
BOOKKEEPING_TABLES = (
    "schema_migrations",
    "alembic_version",
    "_prisma_migrations",
    "flyway_schema_history",
    "driftpilot_*",
)
