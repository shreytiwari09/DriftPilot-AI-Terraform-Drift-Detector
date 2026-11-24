-- Roles for the demo (a Postgres server keeps roles for the whole server, not per database).
CREATE ROLE app_readonly NOLOGIN;
CREATE ROLE app_writer NOLOGIN;

-- DriftPilot's read-only login: it can connect to appdb and read the catalog, nothing else.
CREATE ROLE driftpilot_ro LOGIN PASSWORD 'driftpilot_ro' NOSUPERUSER NOCREATEDB NOCREATEROLE;
REVOKE ALL ON DATABASE appdb FROM PUBLIC;
GRANT CONNECT ON DATABASE appdb TO driftpilot_ro, app;

-- The login that may create (and drop) DriftPilot's scratch databases.
CREATE ROLE driftpilot_scratch LOGIN PASSWORD 'driftpilot_scratch' NOSUPERUSER CREATEDB NOCREATEROLE;
