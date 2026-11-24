# Runbook: the real-AWS demo (S3 only, us-east-1), in order

Run every command from the **repo root**. First time here? Do "Before you start" in `README.md` (policies, users, profiles) and read its "Read this first".
**Never paste an access key into a chat, a file or a screenshot.**

What happens, in one line: **plan** (preview) -> **apply** (create one bucket) -> **scan** (baseline, clean) -> **inject** (change the bucket by hand) ->
**scan** (DriftPilot finds it) -> **revert** (put it back) -> **scan** (clean again) -> **destroy** -> **check-clean**.

## 0. Every session: set up the shell (one terminal, keep using it)

```bash
source .venv/bin/activate
uv pip install --python .venv/bin/python -e ".[dev,demo,db,aws]"   # first time only
unset AWS_REGION AWS_DEFAULT_REGION          # the script sets us-east-1 itself and refuses any other region
export AWS_PROFILE=driftpilot-demo           # the operator profile (can create things)
export DRIFTPILOT_AWS_DEMO=1                 # the drift injector refuses to run without this
aws sts get-caller-identity --query Arn --output text    # shows who you are; read-only
```

## 1. Create it (costs essentially nothing: one empty bucket)

```bash
scripts/aws_demo.sh plan      # read it: 1 bucket + public access block + versioning + encryption (about 5 to add). Nothing is created.
scripts/aws_demo.sh apply     # type us-east-1 when asked. Takes under a minute.
scripts/aws_demo.sh status    # shows the driftpilot-demo-xxxxxxxx bucket
```

**This is the first write ever tried on this account (untested).** If `apply` stops with `AccessDenied` or "explicit deny in a service control policy", that is the account's
own block: nothing to fix in IAM. Run `scripts/aws_demo.sh destroy` and `scripts/aws_demo.sh check-clean` (`destroy` only acts on what it finds tagged `demo=driftpilot` and says so if there is nothing; `check-clean` only reads) and
copy the error text to me. Do not try another region.

## 2. Scan, inject drift, scan, revert (infrastructure drift on the bucket)

DriftPilot reads the demo with the **read-only** profile, so a mistake in DriftPilot cannot change anything.

```bash
export AWS_PROFILE=driftpilot-readonly
driftpilot scan --dir demo/aws --no-llm              # baseline: "No drift detected" (--no-llm: no Gemini key needed)

export AWS_PROFILE=driftpilot-demo                   # the injector needs write access
python scripts/inject_drift.py inject 20 24 25 26    # public block off, a hand tag, versioning suspended, encryption removed

export AWS_PROFILE=driftpilot-readonly
driftpilot scan --dir demo/aws --no-llm              # expect: 20 critical, 25 high, 24 "needs triage" (the AI judges it), 26 critical OR nothing (README, scenario 26)
driftpilot scan --dir demo/aws                       # same with the AI (needs GEMINI_API_KEY); 24 should come out as "codify"

export AWS_PROFILE=driftpilot-demo
python scripts/inject_drift.py revert 26 25 24 20    # put everything back
export AWS_PROFILE=driftpilot-readonly
driftpilot scan --dir demo/aws --no-llm              # "No drift detected"
```

(If you would rather let Terraform do the reverting, `AWS_PROFILE=driftpilot-demo terraform -chdir=demo/aws apply` also fixes 20, 24, 25 and 26. The injector's revert is quicker.)
The scanner also lists buckets named `driftpilot-demo*` that are *not* in Terraform (an "unmanaged" bucket): not part of this runbook, because creating one by hand is another write that was not tried.

## 3. Clean up (do this the same day)

```bash
export AWS_PROFILE=driftpilot-demo
scripts/aws_demo.sh destroy        # lists what will go; type us-east-1 to confirm
scripts/aws_demo.sh check-clean    # must say "Clean"; if not, it lists what is left
rm -f demo/aws/terraform.tfstate demo/aws/terraform.tfstate.backup    # only after a clean destroy
```

Then look with your own eyes: AWS console, **S3**, *General purpose buckets*: no `driftpilot-demo-...`. Optional: delete the access keys and the users if you will not repeat the demo.

If any step fails half way, send me the output of `scripts/aws_demo.sh status` and `check-clean` and the exact error; the state file `demo/aws/terraform.tfstate` stays as it is.

---

# Later, if the account is upgraded (full scope: bucket + security group + RDS, ap-south-1)

Not usable on the current account (EC2 and RDS are denied). Prepare it as described in `README.md`, "Later, if the account is upgraded"
(policies, profiles with region `ap-south-1`, `demo_scope = "full"` and `my_ip_cidr` in `terraform.tfvars`). **The database bills every hour: destroy straight after.**

```bash
unset AWS_REGION AWS_DEFAULT_REGION
export AWS_PROFILE=driftpilot-demo DRIFTPILOT_AWS_DEMO=1
scripts/aws_demo.sh plan           # reads demo_scope = "full" from terraform.tfvars; region ap-south-1
scripts/aws_demo.sh apply          # type ap-south-1 when asked. About 5 to 10 minutes.
scripts/aws_demo.sh status         # the database should say "available"

export AWS_PROFILE=driftpilot-readonly
driftpilot scan --dir demo/aws --config demo/aws/.driftpilot.full.yml --no-llm      # baseline: "No drift detected"
export AWS_PROFILE=driftpilot-demo
python scripts/inject_drift.py inject 20 21 22 24 25      # + security group SSH open, backups off
scripts/aws_demo.sh status                                # wait until the database is "available" again
export AWS_PROFILE=driftpilot-readonly
driftpilot scan --dir demo/aws --config demo/aws/.driftpilot.full.yml --no-llm      # 20 critical, 21 critical, 22 high, 25 high
export AWS_PROFILE=driftpilot-demo
python scripts/inject_drift.py revert 25 24 22 21 20
```

Scenario 23 (`inject 23`) flips `publicly_accessible`; read the README ("Scenario 23") first.

### Database drift: RDS is the live database, your laptop's Docker Postgres is the scratch server

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

### Clean up (full scope)

```bash
unset RDS_ADMIN_URL DRIFTPILOT_DB_URL DRIFTPILOT_RO_PASSWORD DRIFTPILOT_SCRATCH_DB_URL
( cd demo/postgres && docker compose down -v )      # local scratch server and its data
export AWS_PROFILE=driftpilot-demo
scripts/aws_demo.sh destroy        # type ap-south-1 to confirm. Takes a few minutes.
scripts/aws_demo.sh check-clean    # must say "Clean"; it also checks RDS, snapshots, security groups and the budget
rm -f demo/aws/terraform.tfstate demo/aws/terraform.tfstate.backup    # the state holds the database password; only after a clean destroy
```
