# Runbook: the real-AWS demo, in order

Run every command from the **repo root** unless a line starts with `cd`. First time here? Do "Before you start" in `README.md` (users, profiles, your IP in `terraform.tfvars`).
**Never paste an access key, the database password or a database URL into a chat, a file or a screenshot.** The commands below put
secrets into shell variables without printing them.

## 0. Every session: set up the shell (one terminal, keep using it)

```bash
source .venv/bin/activate
uv pip install --python .venv/bin/python -e ".[dev,demo,db,aws]"   # first time only
export AWS_PROFILE=driftpilot-demo          # the operator profile (can create things)
export AWS_REGION=ap-south-1 DRIFTPILOT_AWS_DEMO=1
aws sts get-caller-identity --query Arn --output text    # shows who you are; should be .../dp-demo-operator
```

## 1. Create it (costs money from here on, see README)

```bash
scripts/aws_demo.sh plan      # read it; nothing is created
scripts/aws_demo.sh apply     # type ap-south-1 when asked. Takes about 5 to 10 minutes.
scripts/aws_demo.sh status    # the database should say "available"
```

## A. Infrastructure drift (S3 bucket, security group, RDS settings)

DriftPilot reads the demo with the **read-only** profile, so a mistake in DriftPilot cannot change anything.

```bash
export AWS_PROFILE=driftpilot-readonly
driftpilot scan --dir demo/aws --no-llm              # baseline: "No drift detected" (use --no-llm to avoid needing a Gemini key)
export AWS_PROFILE=driftpilot-demo                   # the injector needs write access
python scripts/inject_drift.py inject 20 21 22 24    # bucket public block off, SSH open to the world, backups off, a tag
scripts/aws_demo.sh status                           # wait until the database status is "available" again (RDS applies the change)
export AWS_PROFILE=driftpilot-readonly
driftpilot scan --dir demo/aws --no-llm              # expect: 20 critical, 21 critical, 22 high; 24 low (without --no-llm the AI judges it)
driftpilot scan --dir demo/aws                       # same with the AI (needs GEMINI_API_KEY); 24 should come out as "codify"
```

Scenario 23 (`inject 23`) flips `publicly_accessible`; read the README section "Scenario 23" first: with the default settings it makes the
database *less* exposed, which is drift but not an alarm.

Put things back (the revert for each scenario), then scan again to see it is clean:

```bash
export AWS_PROFILE=driftpilot-demo
python scripts/inject_drift.py revert 24 22 21 20
scripts/aws_demo.sh status                           # wait for "available"
export AWS_PROFILE=driftpilot-readonly
driftpilot scan --dir demo/aws --no-llm              # "No drift detected"
```

(If you would rather let Terraform do the reverting, `terraform -chdir=demo/aws apply` also fixes 20, 21, 22 and 24. The injector's revert is quicker.)

## B. Database drift: RDS is the live database, your laptop's Docker Postgres is the scratch server

**Why two servers?** DriftPilot builds "what the migration files say" in a throw-away database (`driftpilot_scratch_...`), then compares it with the live
database. It must not create anything on the live one, so the scratch work happens on the local Docker server. Only the *live read* goes to RDS, and it uses a login that can only read.

```bash
# 1. The local scratch server (Docker Desktop must be running)
( cd demo/postgres && docker compose up -d && docker compose ps )     # wait for "healthy"
export DRIFTPILOT_SCRATCH_DB_URL=postgresql://driftpilot_scratch:driftpilot_scratch@localhost:5433/postgres

# 2. The admin URL of RDS, built without printing the password. RDS requires an encrypted connection (sslmode=require).
RDS_HOST=$(terraform -chdir=demo/aws output -raw db_endpoint)
RDS_ADMIN_URL="postgresql://appowner:$(terraform -chdir=demo/aws output -raw db_password)@${RDS_HOST}:5432/appdb?sslmode=require"
psql "$RDS_ADMIN_URL" -c "select version()"          # proves your IP is allowed and the database is up

# 3. Create the roles and the read-only login (a new random password; it is read from the environment, never written down)
export DRIFTPILOT_RO_PASSWORD="$(openssl rand -hex 16)"
psql "$RDS_ADMIN_URL" -v ON_ERROR_STOP=1 -f demo/aws/db_roles.sql
#    the last table must show rolsuper, rolcreatedb, rolcreaterole = f

# 4. Build the "live" database with the demo migrations (the team's deploy)
for f in demo/postgres/migrations/*.sql; do psql "$RDS_ADMIN_URL" -v ON_ERROR_STOP=1 -q -f "$f"; done

# 5. Tell DriftPilot about RDS with the READ-ONLY login
export DRIFTPILOT_DB_URL="postgresql://driftpilot_ro:${DRIFTPILOT_RO_PASSWORD}@${RDS_HOST}:5432/appdb?sslmode=require"

# 6. Prove it is really read-only: this must fail with "cannot execute CREATE TABLE in a read-only transaction"
psql "$DRIFTPILOT_DB_URL" -c "create table should_fail(x int)"

# 7. Scan: nothing has changed yet
driftpilot db scan --dir demo/postgres --no-llm        # "No drift detected"

# 8. Cause drift on RDS by hand (scripts/inject_drift.py 15-19 refuse any non-local database on purpose, so use psql as the admin)
psql "$RDS_ADMIN_URL" -c "ALTER TABLE orders DISABLE ROW LEVEL SECURITY"      # scenario 15: critical
psql "$RDS_ADMIN_URL" -c "GRANT SELECT ON orders TO PUBLIC"                   # scenario 18: critical
psql "$RDS_ADMIN_URL" -c "ALTER TABLE users ADD COLUMN nickname text"         # scenario 19: harmless, codify
driftpilot db scan --dir demo/postgres --no-llm
driftpilot db fix  --dir demo/postgres --no-llm        # prints the SQL to undo, or a new migration file; it never changes the database

# 9. Put it back
psql "$RDS_ADMIN_URL" -c "ALTER TABLE orders ENABLE ROW LEVEL SECURITY" \
  -c "REVOKE SELECT ON orders FROM PUBLIC" -c "ALTER TABLE users DROP COLUMN IF EXISTS nickname"
driftpilot db scan --dir demo/postgres --no-llm        # "No drift detected"
```

**About the read-only login.** `driftpilot_ro` is created with no superuser, no create-database, no create-role rights, can only connect to `appdb`, has
`default_transaction_read_only = on`, and DriftPilot also opens its own session read-only: three separate locks. Step 6 proves it. The password and the
URLs live only in this shell's variables; do not `echo` them, do not `export -p`, do not put them in `.env` files you share. Close the terminal when done
(or `unset RDS_ADMIN_URL DRIFTPILOT_DB_URL DRIFTPILOT_RO_PASSWORD`). DriftPilot hides passwords in its own error messages.

## C. Clean up (do this the same day)

```bash
unset RDS_ADMIN_URL DRIFTPILOT_DB_URL DRIFTPILOT_RO_PASSWORD DRIFTPILOT_SCRATCH_DB_URL
( cd demo/postgres && docker compose down -v )      # local scratch server and its data
export AWS_PROFILE=driftpilot-demo
scripts/aws_demo.sh destroy        # lists what will go; type ap-south-1 to confirm. Takes a few minutes.
scripts/aws_demo.sh check-clean    # must say "Clean"; if not, it lists what is left
rm -f demo/aws/terraform.tfstate demo/aws/terraform.tfstate.backup    # the state holds the database password; only after a clean destroy
```

Then look with your own eyes (README, "Check that nothing is left") and open *Billing and Cost Management, Credits* the next day to see the cost stopped.
Optional: delete the two access keys (IAM, Users, Security credentials) and the two IAM users if you will not repeat the demo.
