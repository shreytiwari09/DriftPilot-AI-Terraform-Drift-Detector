# Real-AWS demo (prepared, not applied): one S3 bucket in us-east-1

This folder builds **one small, real S3 bucket** in your AWS account so DriftPilot can be shown on something real, not only on mocks.
**Nothing here has been applied.** It was written and checked offline (`terraform validate`, an offline `terraform test`, tests with an AWS mock).
The first time anything real happens is when *you* run `scripts/aws_demo.sh apply` and type the region name to confirm.

## Read this first: what was and was not checked

- Your AWS account sits behind an account-wide block (a *service control policy*, "SCP": a rule set above IAM that says which services
  the account may use at all). With read-only calls I measured that **S3 works only in `us-east-1`**, and EC2 and RDS are denied everywhere.
  So the live demo is **S3 only, in `us-east-1`**. That is the "s3 scope" below. The old bigger demo (S3 + security group + database) is kept
  under "Later, if the account is upgraded" and is not used now.
- Only **reading** was verified (`list-buckets` worked and returned an empty list). **Creating a bucket in `us-east-1` is UNTESTED against this
  account.** It may well work (the block let `list-buckets` through), but nobody has tried, and "reading is allowed" does not promise "writing is allowed".
- **If `apply` is denied** (the error says `AccessDenied` or `explicit deny in a service control policy`): that is the account-wide block, not a bug
  in the demo and not something to fix in IAM. Do not try other regions or ways around it. Run `scripts/aws_demo.sh destroy` and `check-clean`
  (see the troubleshooting list) to make sure nothing half-created is left, then show the demo from the recorded runs and the mock tests instead
  (`.venv/bin/pytest tests/test_inject_drift_aws.py` runs all four scenarios against a mock of AWS) and tell me what the error said.

## What it creates (s3 scope, the default)

| Resource | Why | Settings that matter |
| --- | --- | --- |
| S3 bucket `driftpilot-demo-<random>` | the thing the drift scenarios change | all four public-access-block flags **on**, versioning **on**, SSE-S3 encryption (AES256), `force_destroy` so `destroy` empties it first |

That is all: **one bucket, three small settings attached to it**. Every resource carries the tags `demo=driftpilot` and `team=platform`.
The helper script and the drift injector only act on buckets that are named `driftpilot-demo-*` **and** carry the `demo=driftpilot` tag.
A random 8-letter suffix is added to the name because S3 bucket names are shared by everybody in the world.

**Not created, on purpose:** a VPC lookup, security groups, RDS databases, EC2 instances, NAT gateways, load balancers, Elastic IPs, budgets, anything
that can bill by the hour. In this scope the `my_ip_cidr` setting is not needed and is not used.

## What it costs (my estimate, labelled)

An **empty bucket costs essentially nothing**: S3 bills for stored data (GB per month), requests and data transfer, and the bucket holds no objects.
A few dozen requests (Terraform and DriftPilot reading the bucket's settings) are a tiny fraction of a cent. This is my estimate from memory of the
S3 price list, not a quote: check it on the *Amazon S3 pricing* page. Free-plan accounts have a free allowance for S3 requests and storage as well.
Even so, **destroy it when you are done** (`scripts/aws_demo.sh destroy`): "nothing left" is a good habit and `check-clean` proves it.

## Before you start (once)

1. **Tools** (macOS): the AWS CLI (version 1 is installed at `~/.local/bin/aws`; make sure `~/.local/bin` is on your PATH: `aws --version`) and Terraform (installed).
2. **Never use your root login.** *IAM* is AWS's permission system: a *user* is a login for a program, a *policy* is a list of things it may do.
3. **Create the two policies.** AWS console, search **IAM**, **Policies**, **Create policy**, tab **JSON**. Delete the example, paste the whole content of
   `demo/aws/iam-policy-demo-operator-s3.json`, **Next**, name it `DriftPilotDemoOperatorS3`, **Create policy**.
   Repeat with `iam-policy-driftpilot-readonly-s3.json` and the name `DriftPilotReadOnlyS3`.
   These two contain **only S3** (and the tagging lookup), no EC2, no RDS: they match what the account allows.
4. **Users and profiles.** The profile `driftpilot-demo` already exists on this laptop. If its user is not yet allowed to create buckets, attach
   `DriftPilotDemoOperatorS3` to it (IAM, Users, the user, **Add permissions**, **Attach policies directly**). For scanning, create a second user
   `dp-demo-readonly` with `DriftPilotReadOnlyS3`, make an access key (*Security credentials*, **Create access key**, **Command Line Interface**),
   and store it with `aws configure --profile driftpilot-readonly` (region: `us-east-1`; output: `json`).
   **Never paste an access key or secret in a chat, a file, an email or a screenshot.** If one ever leaks, delete it (IAM, user, Security credentials) and make a new one.
   (Keep user names starting with `dp-demo-`: they are outside the scanner's `driftpilot-demo*` pattern, so they are not reported as unmanaged.)
5. **Check that the profile works** (this only asks AWS "who am I?" and "what buckets exist?"; both are read-only):

   ```bash
   AWS_PROFILE=driftpilot-demo aws sts get-caller-identity
   AWS_PROFILE=driftpilot-demo aws s3api list-buckets --region us-east-1
   ```

There is **no `terraform.tfvars` to fill in** for this scope.

## Run it (details and exact order: `RUNBOOK.md`)

```bash
export AWS_PROFILE=driftpilot-demo
scripts/aws_demo.sh plan          # shows what would be created (one bucket and 3 settings); changes nothing
scripts/aws_demo.sh apply         # shows the plan again, then waits until you type us-east-1
scripts/aws_demo.sh status        # lists the live demo bucket
...                               # scan, inject drift, scan again, revert (RUNBOOK.md)
scripts/aws_demo.sh destroy       # shows what will be deleted, waits until you type us-east-1
scripts/aws_demo.sh check-clean   # exits 1 if anything tagged demo=driftpilot is still there
```

The script refuses anything that is not safe: no named profile, AWS keys in the environment, or a region other than `us-east-1`.
**Terraform state** is Terraform's notebook of what it built; here it is the file `demo/aws/terraform.tfstate`, on this laptop only and gitignored.
(In this scope it holds no password. Delete it after a clean destroy anyway.)

## The drift scenarios (20, 24, 25, 26)

`scripts/inject_drift.py` changes the *real* demo bucket by hand, the way a person in a hurry would. It needs `DRIFTPILOT_AWS_DEMO=1` and your
profile; the region defaults to `us-east-1` (and any other is refused). It **refuses any bucket that is not tagged `demo=driftpilot`**
(and named `driftpilot-demo-*`). Each scenario has a revert. Scenarios 21, 22 and 23 (security group, database) refuse to run in this scope.

| # | What the "person in a hurry" does | DriftPilot should say |
| --- | --- | --- |
| 20 | turns the bucket's S3 public access block off | critical, revert (never softened by the AI) |
| 24 | adds a harmless tag `reviewed-by=hand` to the bucket | low, codify (keep it, update the code) |
| 25 | suspends the bucket's versioning | high, revert |
| 26 | removes the bucket's default encryption setting | critical, revert (see the honest note below) |

```bash
export DRIFTPILOT_AWS_DEMO=1 AWS_PROFILE=driftpilot-demo
.venv/bin/python scripts/inject_drift.py inject 20 24 25 26
.venv/bin/python scripts/inject_drift.py revert 26 25 24 20
```

**Honest note on scenario 26.** Since 2023 S3 encrypts *every* bucket with its own default key (SSE-S3). "Removing" the encryption setting
therefore just puts the bucket back on that default. Depending on how the AWS provider reports that, DriftPilot may show a critical
"encryption configuration deleted", a small change, or **nothing at all**. That would not be a DriftPilot bug: the data is still encrypted. I could not test this
(no write access to AWS). Treat 20, 24 and 25 as the main demo and 26 as a bonus: if it shows nothing, say so and move on.
(Rules-only, 24 shows as "needs triage": the low-severity tag call is made by the AI, so run that scan without `--no-llm` if you want the "codify" answer.)

## Check that nothing is left

`scripts/aws_demo.sh check-clean` does this by command (it lists buckets and tags; it does not need EC2 or RDS). To see it with your own eyes:
AWS console, **S3**, **General purpose buckets**: there is no `driftpilot-demo-...`. (S3 lists all regions together, so a leftover would show up here.)
Then delete `demo/aws/terraform.tfstate*` if still there.

## What the two IAM policies allow, and why

They were derived from what Terraform, the helper script, the drift injector and the scanner actually call, not copied from "AdministratorAccess".
**They have not been tried against real AWS.** If a step ends in `AccessDenied`, the error names the missing action: add it in the console and tell me.
(But if the message says *service control policy*, no IAM edit can fix it: see "Read this first".)

`iam-policy-driftpilot-readonly-s3.json` (for `driftpilot scan`; changes nothing):
- `s3:ListAllMyBuckets`, `s3:GetBucketLocation` (the scanner lists buckets and checks their region);
- read-only `ListBucket`, `GetBucket*`, `GetEncryptionConfiguration`, `GetLifecycleConfiguration`, `GetReplicationConfiguration`, `GetAccelerateConfiguration`
  on `driftpilot-demo-*` buckets only (Terraform's refresh reads these sub-settings);
- `tag:GetResources`, limited to `us-east-1` (a tag lookup).

`iam-policy-demo-operator-s3.json` = the read-only list, plus on `driftpilot-demo-*` only: `CreateBucket`, `DeleteBucket`, `PutBucketTagging`,
`PutBucketPublicAccessBlock`, `PutBucketVersioning`, `PutEncryptionConfiguration`, and `ListBucketVersions`, `DeleteObject`, `DeleteObjectVersion` (so `force_destroy` can empty the bucket).

**Wildcards I had to keep, and why:** `Resource: "*"` on `ListAllMyBuckets`, `GetBucketLocation` and `tag:GetResources` (AWS cannot limit these list calls to one bucket;
the scanner must see the whole account to find what is not in Terraform); `s3:GetBucket*` (read-only, demo buckets only: Terraform's S3 refresh reads about a dozen separate
`GetBucket...` settings); `driftpilot-demo-*` in names instead of the exact bucket name, because the random suffix is only known after creation.
Each file is plain ASCII JSON and under 6,144 non-whitespace characters, the limit for a managed policy.

## Troubleshooting

- *`AccessDenied` / "explicit deny in a service control policy" on `apply`*: see "Read this first". Run `destroy` and `check-clean` to make sure nothing half-built is left (for example the bucket was created but one of its settings was denied).
- *`AccessDenied` that names an action*: add that action to `DriftPilotDemoOperatorS3` (or the read-only one) in the console and run the step again.
- *`BucketAlreadyExists`*: extremely unlikely (random suffix). Run `apply` again; it picks a new suffix.
- *Terraform says the plan file is stale*: run `apply` again; it re-plans every time.
- *`refusing to run: ... runs in us-east-1`*: you have `AWS_REGION` or `AWS_DEFAULT_REGION` set to something else. `unset AWS_REGION AWS_DEFAULT_REGION`.
- *Scenario 26 shows nothing*: see the honest note above.

---

# Later, if the account is upgraded (the "full" scope; not used now)

Only for an account that is allowed to use EC2 and RDS in `ap-south-1` (Mumbai). It needs the account to be upgraded first (a payment method), so **do
not use this on the current account**: EC2 and RDS are denied there, and every command below would just fail.

It adds to the bucket a **security group** and one small **RDS PostgreSQL** database. **This one costs real money by the hour; destroy it straight after.**

## What the full scope creates

| Resource | Why | Settings that matter |
| --- | --- | --- |
| S3 bucket `driftpilot-demo-<random>` | scenarios 20, 24, 25, 26 | as above |
| Security group `driftpilot-demo-db` | scenario 21 | port 5432 only from **your** IP (a `/32`). `0.0.0.0/0` is rejected by a validation rule |
| RDS PostgreSQL 16 `driftpilot-demo-db` | scenarios 22 and 23, and the database-drift demo | `db.t4g.micro`, 20 GB gp3, single-AZ, encrypted, `publicly_accessible = true` (so your laptop can connect; the security group limits who), backups kept 1 day, no final snapshot, no deletion protection, no Performance Insights, no enhanced monitoring |
| random password | the database login | generated by Terraform, hidden in output, stored in local state |
| AWS Budgets alert (optional, off by default) | warns you by email at 80 % of US$20 | `enable_budget_guard = true` plus your email in `terraform.tfvars` |

**Not created on purpose** (each can cost money by itself): NAT gateway, load balancer, EC2 instances, Elastic IPs, Secrets Manager, CloudTrail trails,
Multi-AZ, read replicas, Performance Insights.

## What the full scope costs (my estimates, labelled)

| Piece | My estimate | Where to check |
| --- | --- | --- |
| RDS `db.t4g.micro` in ap-south-1 | about US$0.02 per hour | RDS for PostgreSQL pricing page, region Asia Pacific (Mumbai) |
| 20 GB gp3 storage | about US$0.003 per hour (US$2 to 3 per month) | same page, "Storage" |
| Public IPv4 address of the database | about US$0.005 per hour | VPC pricing page, "Public IPv4 Address" |
| S3 bucket (empty), security group in the default VPC, Budgets (first budgets) | about nothing | S3, VPC, Budgets pricing pages |

Roughly **US$0.03 per hour, about US$0.7 per day**; a forgotten month is roughly US$20 to 25. These are estimates written from memory of the price lists, not quotes.
A **credit** is prepaid AWS money: usage is billed as normal, then credits are subtracted, so the balance in *Billing, Credits* goes down while the database exists.

## Switching on the full scope

1. **Policies:** create `DriftPilotDemoOperator` from `iam-policy-demo-operator.json` and `DriftPilotReadOnly` from `iam-policy-driftpilot-readonly.json` (these have the EC2, RDS and
   Budgets statements, limited to `ap-south-1`); attach them to the operator and read-only users instead of the S3 ones. They must be *customer managed policies* (an inline policy is limited to 2,048 characters).
2. **Profiles with region `ap-south-1`:** `aws configure --profile driftpilot-demo` and `--profile driftpilot-readonly`; also `brew install libpq` (gives `psql`) and Docker Desktop for the database demo.
3. **Your IP and the scope** in `demo/aws/terraform.tfvars` (gitignored, never commit it):

   ```bash
   curl -s https://checkip.amazonaws.com        # for example 198.51.100.9
   cd demo/aws && cp terraform.tfvars.example terraform.tfvars
   # edit terraform.tfvars:   demo_scope = "full"      my_ip_cidr = "198.51.100.9/32"
   ```

   If your IP changes later (new Wi-Fi, mobile hotspot), update the file and `apply` again, or you will get connection time-outs.
4. **Run:** the same `scripts/aws_demo.sh plan | apply | status | destroy | check-clean`; the script reads `demo_scope = "full"` and then uses `ap-south-1` (you type `ap-south-1` to confirm).
   `apply` takes roughly 5 to 10 minutes (RDS is slow to start). The state file then **contains the database password in plain text**: gitignored, never share it; delete it after a clean destroy.
5. **Scan with the full settings:** `driftpilot scan --dir demo/aws --config demo/aws/.driftpilot.full.yml --no-llm` (region `ap-south-1`, also looks at security groups and IAM users).
6. **Scenarios 21 to 23** work only in this scope (set `DRIFTPILOT_AWS_DEMO=1`; the region defaults to `ap-south-1`):

   | # | What the "person in a hurry" does | DriftPilot should say |
   | --- | --- | --- |
   | 21 | opens SSH (port 22) to `0.0.0.0/0` on the security group | critical, revert (never softened) |
   | 22 | sets database backup retention to 0 days | high, revert |
   | 23 | flips `publicly_accessible` (see below) | depends on the direction |

   **Scenario 23, which direction is drift?** The code says `publicly_accessible = true`. The injector sets the *opposite*, `false`: real drift, but it makes the database *safer*, so
   the "made public" rule does not fire and the change goes to the AI or to a person. For the dramatic direction (a private database made public, always critical): set
   `db_publicly_accessible = false` in `terraform.tfvars`, `apply`, then `export DRIFTPILOT_AWS_DEMO_PUBLIC=false` and inject 23. With the database private you cannot connect from your laptop, so use that for the infrastructure part only.
   RDS changes take a few minutes: wait until `status` shows `available` before scanning.
7. **The database-drift demo on RDS:** the `RUNBOOK.md` section "Later: the full scope" has the steps.
8. **Check that nothing is left** (console, region switched to **Asia Pacific (Mumbai) ap-south-1**): RDS *Databases*, *Snapshots* (Manual, System) and *Automated backups* (Current Region, Retained) empty; S3 has no `driftpilot-demo-...`;
   EC2 *Security Groups* has no `driftpilot-demo-db`; *Snapshots*, *Volumes* and *Elastic IPs* empty; *Billing and Cost Management* shows the daily cost falling to about zero.

Full-scope policy notes: EC2 `CreateSecurityGroup` only when the request is tagged `demo=driftpilot`; rule changes, delete and tag edits only on groups that already carry the tag; RDS create only when tagged,
modify/delete only on `driftpilot-demo-*` databases that carry the tag; `iam:CreateServiceLinkedRole` for `rds.amazonaws.com` only (the first RDS database in an account makes AWS create a helper role);
EC2, RDS and the tagging call are limited to `ap-south-1` with `aws:RequestedRegion`. Extra full-scope troubleshooting: *timeout connecting to the database* = your IP changed or the instance is still `creating`;
*no default VPC* or `DBSubnetGroupDoesNotExistFault` = console, VPC, *Your VPCs*, *Actions*, *Create default VPC*; *`AccessDenied` on the first RDS create* = the service-linked-role statement is missing.
