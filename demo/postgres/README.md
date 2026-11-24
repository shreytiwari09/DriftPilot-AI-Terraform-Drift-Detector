# Postgres demo (database schema drift)

A local Postgres in Docker, with three migration files, so you can watch DriftPilot find hand changes to a database.
Nothing here touches the cloud, GitHub or your real data. The passwords are demo values for a container that only
listens on `127.0.0.1`.

## The idea in one minute

- **Migration files** (`migrations/*.sql`) are the team's record of how the database should look.
- Someone fixes something directly on the live database and forgets the migration. That is **schema drift**.
- DriftPilot builds the schema the migrations describe in a throw-away database, reads the live database
  (read-only), compares the two, judges each difference, and proposes a fix: SQL to undo it, or a new migration file.

Two databases are involved, both on the one server in this container:

| Database | What it is |
| --- | --- |
| `appdb` | The "live" database. Built from the migrations when the container first starts. You change it by hand to cause drift. |
| `driftpilot_scratch_<random>` | Made by DriftPilot for each scan, filled by running the migrations, read, and dropped again. It is DriftPilot's idea of "what the migrations say". |

Two logins: `driftpilot_ro` can only read `appdb` (it cannot write: DriftPilot also opens its session read-only);
`driftpilot_scratch` may create and drop databases (only ones named `driftpilot_scratch_*`).

## Steps

1. Start it (needs Docker Desktop running):

   ```bash
   cd demo/postgres
   docker compose up -d
   docker compose ps          # wait until the status says "healthy"
   ```

2. Tell DriftPilot where the databases are. The URLs are secrets, so they are read from the environment, never from a file:

   ```bash
   export DRIFTPILOT_DB_URL=postgresql://driftpilot_ro:driftpilot_ro@localhost:5433/appdb
   export DRIFTPILOT_SCRATCH_DB_URL=postgresql://driftpilot_scratch:driftpilot_scratch@localhost:5433/postgres
   ```

3. Install the database support once (from the repo root): `uv pip install --python .venv/bin/python -e ".[dev,demo,db,aws]"`

4. Scan. Nothing has changed yet, so it says "No drift detected":

   ```bash
   driftpilot db scan --dir demo/postgres --no-llm
   ```

5. Cause drift (from the repo root). Scenarios 15-19 (local only, they only connect to localhost):

   | # | Hand change | DriftPilot says |
   | --- | --- | --- |
   | 15 | `ALTER TABLE orders DISABLE ROW LEVEL SECURITY` | critical / revert |
   | 16 | `ALTER TABLE users ALTER COLUMN email DROP NOT NULL` | high / revert |
   | 17 | `ALTER TABLE users ADD COLUMN ssn text` | high / investigate (looks like personal data) |
   | 18 | `GRANT SELECT ON orders TO PUBLIC` | critical / revert |
   | 19 | `ALTER TABLE users ADD COLUMN nickname text` | medium / codify (harmless, keep it) |

   ```bash
   python scripts/inject_drift.py inject 15
   driftpilot db scan --dir demo/postgres --no-llm
   ```

6. See the fixes DriftPilot would propose (it only prints them; it never changes the database):

   ```bash
   driftpilot db fix --dir demo/postgres --no-llm
   ```

   Reverts show **Suggested SQL (review before running)**. A change worth keeping (scenario 19) gets a **new migration
   file**, tested first: DriftPilot builds a fresh scratch database from every migration plus the new file and checks it
   matches the live database. "Schema built from migrations matches the live database (0 differences)" is that proof.
   Add `--write` to save the migration file into `migrations/`.

7. Undo the drift (puts the database back):

   ```bash
   python scripts/inject_drift.py revert 15 16 17 18 19
   ```

8. Remove the container and its data when you are done:

   ```bash
   cd demo/postgres && docker compose down -v
   ```

Without `--no-llm` (and with `GEMINI_API_KEY` set) the AI judges the changes the rules do not decide, such as a changed
default or a new index. Row-level security off, a dropped policy and a grant to PUBLIC are always `critical`: the AI
cannot play them down.

## Settings

`.driftpilot.yml` in this folder: `database.migrations` (the folder), `database.schemas` (default `public`),
`database.ignore` (table globs to leave out), and the names of the environment variables that hold the URLs.

## Tests that use this container

```bash
DRIFTPILOT_TEST_DB_URL=postgresql://app:app@localhost:5433/postgres .venv/bin/pytest -m postgres
```
