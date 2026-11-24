# Running DriftPilot outside GitHub Actions

> **Untested templates.** Everything in this folder is a starting point. None of it has been applied to a
> real AWS or Google Cloud account, and nothing here is deployed by DriftPilot. Read each file, change the
> placeholders (`CHANGE_ME`), and try it in a sandbox account first.

DriftPilot is one container image (`Dockerfile` in the repo root: Python 3.12, a pinned Terraform, the
`driftpilot` command). The GitHub Action and these templates run the **same command**, `driftpilot action`.
Outside GitHub Actions it prints the report to the log and writes `driftpilot-outputs.json`
(`drift-found`, `critical-count`, `finding-count`, `unmanaged-count`, `run-id`) instead of GitHub's output files.

| Template | Trigger | Folder |
| --- | --- | --- |
| (a) EventBridge Scheduler -> ECS Fargate task | a timetable (for example every 6 hours) | `aws-ecs-schedule/` |
| (b) EventBridge rule on CloudTrail events -> the same task | a change in AWS, with who did it | `aws-ecs-cloudtrail-event/` |
| (c) Cloud Run job + Cloud Scheduler | a timetable on Google Cloud | `gcp-cloud-run/` |
| (d) plain cron on any VM | a timetable on a machine you already have | `cron/` |

## Try it locally first (this part is tested)

```bash
docker build -t driftpilot:dev .
docker run --rm driftpilot:dev version
# replay a recorded plan and a recorded CloudTrail event, no cloud account needed:
docker run --rm -v "$PWD/tests/fixtures:/fx:ro" driftpilot:dev \
  scan --plan-json /fx/github/s2_required_approvals_reduced.json --no-llm
```

## Getting your Terraform code into the container

A container started by a schedule has no checkout. Either build a small image of your own that adds the code
(`deploy/Dockerfile.with-code.example`, rebuilt when the code changes), or mount a checkout (the VM template).

## Settings the container reads

| Variable | What it is |
| --- | --- |
| `DRIFTPILOT_WORKING_DIRECTORY` | the Terraform folder inside the container (mount or clone it there) |
| `DRIFTPILOT_CHECKS` | `infrastructure` (default), `database` (Postgres schema drift) or both: `infrastructure,database` |
| `DRIFTPILOT_DB_URL`, `DRIFTPILOT_SCRATCH_DB_URL` | **secrets** for the database check: a read-only login on the live database, and a login on a server where DriftPilot may create and drop its own `driftpilot_scratch_*` databases |
| `DRIFTPILOT_EVENT_PATH` / `DRIFTPILOT_EVENT_JSON` | a CloudTrail event, as a file or as JSON text (who changed what) |
| `DRIFTPILOT_MODE` | `advise` (issues only) or `open-prs` |
| `DRIFTPILOT_LLM_API_KEY`, `DRIFTPILOT_GITHUB_TOKEN`, `GITHUB_TOKEN`, `GITHUB_REPOSITORY` | **secrets** and the repository to open issues in |
| `DRIFTPILOT_HISTORY_BRANCH` | where drift history is stored in the repository (optional) |
| `DRIFTPILOT_OUTPUTS_FILE` | where to write the outputs JSON (default `driftpilot-outputs.json`) |

## Where the secrets go

Never put a token in a template, an image or a repository. Keep them in the platform's secret store and pass
them to the container as environment variables at start-up:

- AWS: Secrets Manager or SSM Parameter Store (SecureString), referenced in the ECS task definition `secrets`
  block. The task *execution* role needs permission to read exactly those secrets.
- Google Cloud: Secret Manager, mounted as environment variables on the Cloud Run job.
- VM: a root-only env file (`chmod 600`) read by the cron line, or the system's own secret tooling.

## Read-only AWS permissions

DriftPilot never applies changes, so the role it runs as should not be able to either.

1. **What `terraform plan -refresh-only` reads.** One read-only permission set for every service your Terraform
   manages. The AWS managed policies `ReadOnlyAccess` or `SecurityAudit` plus `ViewOnlyAccess` are the quick start;
   a tighter, hand-written list of `Describe*`, `Get*` and `List*` actions for only your services is better.
2. **The Terraform state.** Read the state file (`s3:GetObject` and `s3:ListBucket` on the state bucket and key, and
   `kms:Decrypt` if it is encrypted). Runs use `-lock=false`, so no lock-table write is needed.
3. **The AWS scanner** (finds buckets, security groups and IAM users that are not in Terraform):
   `s3:ListAllMyBuckets`, `s3:GetBucketLocation`, `ec2:DescribeSecurityGroups`, `iam:ListUsers`.
4. **Secrets**: the *execution* role reads the secrets above; the *task* role does not need them.

For cross-account scans, give the task role `sts:AssumeRole` on a read-only role in each target account.
To reach Google Cloud from AWS (or the reverse) use workload identity federation, not long-lived keys.

## What "who changed it" needs

Template (b) uses CloudTrail management events. A trail must be logging them (AWS documents that EventBridge only
sees events from an active trail). The event gives the caller, the API call and its request parameters, which
DriftPilot cleans, attaches to the matching resource, and shows in the issue ("Changed by ...") and to the AI.
Matching is by resource name or ID, so treat it as a strong hint.
