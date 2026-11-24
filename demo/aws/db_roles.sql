-- Roles for the RDS demo database. Run ONCE as the master login, BEFORE the demo migrations:
--
--   export DRIFTPILOT_RO_PASSWORD="$(openssl rand -hex 16)"      # a new random password; never print it
--   psql "$RDS_ADMIN_URL" -v ON_ERROR_STOP=1 -f demo/aws/db_roles.sql
--
-- (RUNBOOK.md, part B, has the full steps.) The password is read from the environment inside psql, so it is
-- never written in this file and never appears on a command line.

\set ro_password `printf '%s' "$DRIFTPILOT_RO_PASSWORD"`

-- Stop early if the password variable was not set.
SELECT length(:'ro_password') < 16 AS password_too_short \gset
\if :password_too_short
  \echo 'DRIFTPILOT_RO_PASSWORD is empty or shorter than 16 characters: set it first (see RUNBOOK.md).'
  \quit
\endif

-- The two roles the demo migrations hand out privileges to (the same names demo/postgres uses).
CREATE ROLE app_readonly NOLOGIN;
CREATE ROLE app_writer NOLOGIN;

-- DriftPilot's read-only login. It must really be read-only:
--   * no superuser, no create-database, no create-role, no replication
--   * it can connect to appdb and read the catalog; it owns nothing and is granted nothing else
--   * every session it opens is read-only by default, even if someone tries to write
--   * at most 3 connections at once
CREATE ROLE driftpilot_ro LOGIN PASSWORD :'ro_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION CONNECTION LIMIT 3;
ALTER ROLE driftpilot_ro SET default_transaction_read_only = on;

REVOKE ALL ON DATABASE appdb FROM PUBLIC;
GRANT CONNECT ON DATABASE appdb TO driftpilot_ro;

-- Check it: this lists the role's flags. rolsuper, rolcreatedb, rolcreaterole must all say "f".
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication
FROM pg_roles WHERE rolname = 'driftpilot_ro';
