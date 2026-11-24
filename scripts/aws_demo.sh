#!/usr/bin/env bash
# Safe wrapper around the real-AWS demo in demo/aws (Terraform + the AWS CLI).
#
#   AWS_PROFILE=driftpilot-demo scripts/aws_demo.sh plan         # show what would be created (changes nothing)
#   AWS_PROFILE=driftpilot-demo scripts/aws_demo.sh apply        # create it (asks you to type the region)
#   AWS_PROFILE=driftpilot-demo scripts/aws_demo.sh status       # list the live demo resources
#   AWS_PROFILE=driftpilot-demo scripts/aws_demo.sh destroy      # delete it all (asks you to type the region)
#   AWS_PROFILE=driftpilot-demo scripts/aws_demo.sh check-clean  # exit 1 if anything tagged demo=driftpilot is left
#
# Scope: "s3" (default) is one S3 bucket in us-east-1. "full" adds a security group and a small RDS database in
# ap-south-1. Set `demo_scope = "full"` in demo/aws/terraform.tfvars (or DEMO_SCOPE=full for one command).
#
# It only works with a named profile (AWS_PROFILE), never with keys in environment variables, and only in
# the scope's region. `apply` and `destroy` print what they will do and wait for you to type the region name.
set -euo pipefail

SCOPE="s3" # s3 or full; resolved by resolve_scope
REGION=""  # us-east-1 for s3, ap-south-1 for full; set by resolve_scope
TAG_KEY="demo"
TAG_VALUE="driftpilot"
NAME_PREFIX="driftpilot-demo"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="${HERE}/../demo/aws"
PLAN_FILE="${DEMO_DIR}/.demo.plan" # holds the database password: gitignored (*.plan), deleted after use

die() {
  echo "error: $*" >&2
  exit 1
}

usage() {
  sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-1}"
}

# The scope comes from DEMO_SCOPE, else from `demo_scope = "..."` in terraform.tfvars, else "s3".
# The region follows the scope; any other region is refused below.
resolve_scope() {
  local file="${DEMO_DIR}/terraform.tfvars"
  SCOPE="${DEMO_SCOPE:-}"
  if [[ -z "${SCOPE}" && -f "${file}" ]]; then
    SCOPE="$(sed -n 's/^[[:space:]]*demo_scope[[:space:]]*=[[:space:]]*"\([A-Za-z0-9_-]*\)".*/\1/p' "${file}" | tail -n 1)"
  fi
  SCOPE="${SCOPE:-s3}"
  case "${SCOPE}" in
    s3) REGION="us-east-1" ;;
    full) REGION="ap-south-1" ;;
    *) die "unknown demo scope '${SCOPE}' (use s3 or full)" ;;
  esac
}

require_safe_environment() {
  resolve_scope
  [[ -n "${AWS_PROFILE:-}" ]] || die "AWS_PROFILE is not set. Run:  export AWS_PROFILE=driftpilot-demo  (see demo/aws/README.md)"
  if [[ -n "${AWS_ACCESS_KEY_ID:-}" || -n "${AWS_SECRET_ACCESS_KEY:-}" || -n "${AWS_SESSION_TOKEN:-}" ]]; then
    die "AWS keys are set in the environment. Unset them and use a profile (aws configure --profile ...)."
  fi
  if [[ -n "${AWS_REGION:-}" && "${AWS_REGION}" != "${REGION}" ]]; then
    die "AWS_REGION is ${AWS_REGION}; the ${SCOPE} scope of this demo only runs in ${REGION}."
  fi
  if [[ -n "${AWS_DEFAULT_REGION:-}" && "${AWS_DEFAULT_REGION}" != "${REGION}" ]]; then
    die "AWS_DEFAULT_REGION is ${AWS_DEFAULT_REGION}; the ${SCOPE} scope of this demo only runs in ${REGION}."
  fi
  export AWS_REGION="${REGION}" AWS_DEFAULT_REGION="${REGION}"
  command -v aws >/dev/null || die "the AWS CLI is not installed (see demo/aws/README.md, step 1)"
  command -v terraform >/dev/null || die "terraform is not installed"
}

show_identity() {
  local arn
  arn="$(aws sts get-caller-identity --query Arn --output text)" || die "cannot use profile '${AWS_PROFILE}' (expired or wrong keys?)"
  echo "Profile: ${AWS_PROFILE}"
  echo "Acting as: ${arn}"
  echo "Scope: ${SCOPE}"
  echo "Region: ${REGION}"
}

# Only the "full" scope needs terraform.tfvars (your IP for the database firewall).
require_tfvars() {
  [[ "${SCOPE}" == "full" ]] || return 0
  [[ -f "${DEMO_DIR}/terraform.tfvars" ]] || die "demo/aws/terraform.tfvars is missing. Copy terraform.tfvars.example to terraform.tfvars and put your IP in it."
  if grep -Eq '^[[:space:]]*my_ip_cidr[[:space:]]*=[[:space:]]*"203\.0\.113\.7/32"' "${DEMO_DIR}/terraform.tfvars"; then
    die "terraform.tfvars still has the example IP (203.0.113.7/32). Put your own address there."
  fi
}

tf() {
  terraform -chdir="${DEMO_DIR}" "$@"
}

# plan/apply/destroy always get the scope from here, so the script and Terraform cannot disagree.
tf_scoped() {
  local sub="$1"
  shift
  tf "${sub}" -var "demo_scope=${SCOPE}" "$@"
}

confirm_region() {
  local what="$1" answer
  echo
  echo "This will ${what}."
  if [[ "${SCOPE}" == "full" ]]; then
    echo "AWS usage draws down your credits while the database exists. Destroy the demo straight after use."
  else
    echo "An empty bucket costs essentially nothing, but destroy the demo when you are done."
  fi
  printf 'To continue, type the region name (%s): ' "${REGION}"
  read -r answer || answer=""
  [[ "${answer}" == "${REGION}" ]] || die "not confirmed, nothing was changed."
}

# Everything below fills the global arrays instead of printing from a subshell, so that a failed AWS call
# stops the whole script: a check that cannot see AWS must never report "clean".
TAGGED=()
LEFT=()

# Runs one read-only AWS CLI query and returns its items, one per line, in the variable QUERY_RESULT.
QUERY_RESULT=""
query() {
  local what="$1" out
  shift
  out="$(aws "$@" --output text)" || die "the AWS call for '${what}' failed, so I cannot tell what exists"
  QUERY_RESULT="$(tr '\t' '\n' <<<"${out}" | sed '/^$/d; /^None$/d')"
}

# Adds the last query's items to LEFT with a label.
add_left() {
  local label="$1" line
  while IFS= read -r line; do
    [[ -z "${line}" ]] || LEFT+=("${label}: ${line}")
  done <<<"${QUERY_RESULT}"
}

# Fills TAGGED with the buckets named driftpilot-demo-* that carry demo=driftpilot. Plain S3 calls only (the
# "s3" scope never depends on the tagging API, which has not been tried against this account).
find_tagged_s3() {
  local name value
  TAGGED=()
  query "S3 buckets" s3api list-buckets --query "Buckets[?starts_with(Name, '${NAME_PREFIX}-')].Name"
  while IFS= read -r name; do
    [[ -n "${name}" ]] || continue
    # A bucket whose tags cannot be read is simply not listed here; check-clean still lists it by name.
    value="$(aws s3api get-bucket-tagging --bucket "${name}" \
      --query "TagSet[?Key=='${TAG_KEY}'].Value" --output text 2>/dev/null)" || value=""
    [[ "${value}" == "${TAG_VALUE}" ]] && TAGGED+=("arn:aws:s3:::${name}")
  done <<<"${QUERY_RESULT}"
  return 0
}

# Fills TAGGED with the ARN of everything demo=driftpilot: via the tagging API (S3, security groups, RDS...) in
# the "full" scope, via S3 alone in the "s3" scope.
find_tagged() {
  local line
  if [[ "${SCOPE}" == "s3" ]]; then
    find_tagged_s3
    return 0
  fi
  TAGGED=()
  query "tagged resources" resourcegroupstaggingapi get-resources \
    --tag-filters "Key=${TAG_KEY},Values=${TAG_VALUE}" --query 'ResourceTagMappingList[].ResourceARN'
  while IFS= read -r line; do
    [[ -z "${line}" ]] || TAGGED+=("${line}")
  done <<<"${QUERY_RESULT}"
}

# Fills LEFT with one line per leftover; empty means the account is clean.
find_leftovers() {
  local line
  LEFT=()
  find_tagged
  for line in "${TAGGED[@]+"${TAGGED[@]}"}"; do LEFT+=("tagged resource: ${line}"); done
  if [[ "${SCOPE}" == "full" ]]; then
    find_leftovers_full
  fi
  query "S3 buckets" s3api list-buckets --query "Buckets[?starts_with(Name, '${NAME_PREFIX}-')].Name"
  add_left "S3 bucket"
}

# Extra leftovers of the "full" scope: database, snapshots, security groups, budget. Never run in the "s3" scope
# (EC2 and RDS are not reachable there, and nothing of the sort is created).
find_leftovers_full() {
  local account
  query "RDS instances" rds describe-db-instances \
    --query "DBInstances[?starts_with(DBInstanceIdentifier, '${NAME_PREFIX}')].DBInstanceIdentifier"
  add_left "RDS instance"
  query "RDS snapshots" rds describe-db-snapshots \
    --query "DBSnapshots[?starts_with(DBInstanceIdentifier, '${NAME_PREFIX}')].DBSnapshotIdentifier"
  add_left "RDS snapshot"
  query "RDS automated backups" rds describe-db-instance-automated-backups \
    --query "DBInstanceAutomatedBackups[?starts_with(DBInstanceIdentifier, '${NAME_PREFIX}')].DBInstanceIdentifier"
  add_left "RDS automated backup"
  query "EBS snapshots" ec2 describe-snapshots --owner-ids self \
    --filters "Name=tag:${TAG_KEY},Values=${TAG_VALUE}" --query 'Snapshots[].SnapshotId'
  add_left "EBS snapshot"
  query "security groups" ec2 describe-security-groups \
    --filters "Name=tag:${TAG_KEY},Values=${TAG_VALUE}" --query 'SecurityGroups[].GroupId'
  add_left "security group"
  query "account id" sts get-caller-identity --query Account
  account="${QUERY_RESULT}"
  # The budget is optional and free; a missing permission here is only a warning.
  if QUERY_RESULT="$(aws budgets describe-budgets --region us-east-1 --account-id "${account}" \
    --query "Budgets[?starts_with(BudgetName, '${NAME_PREFIX}')].BudgetName" --output text 2>/dev/null)"; then
    add_left "budget"
  else
    echo "note: could not read budgets (no permission?); the budget is optional and free." >&2
  fi
}


cmd_plan() {
  require_safe_environment
  show_identity
  require_tfvars
  tf init -input=false >/dev/null
  tf_scoped plan -input=false
}

cmd_apply() {
  require_safe_environment
  show_identity
  require_tfvars
  tf init -input=false >/dev/null
  trap 'rm -f "${PLAN_FILE}"' EXIT
  tf_scoped plan -input=false -out="${PLAN_FILE}"
  if [[ "${SCOPE}" == "full" ]]; then
    confirm_region "CREATE the resources above in your AWS account (an S3 bucket, a security group and one small RDS database)"
  else
    confirm_region "CREATE the resources above in your AWS account (one S3 bucket in ${REGION})"
  fi
  tf apply -input=false "${PLAN_FILE}"
  echo
  echo "Done. Next steps: demo/aws/RUNBOOK.md. When finished: scripts/aws_demo.sh destroy"
}

cmd_status() {
  require_safe_environment
  show_identity
  echo
  if [[ "${SCOPE}" == "full" ]]; then
    echo "RDS instances named ${NAME_PREFIX}*:"
    aws rds describe-db-instances \
      --query "DBInstances[?starts_with(DBInstanceIdentifier, '${NAME_PREFIX}')].[DBInstanceIdentifier,DBInstanceStatus,DBInstanceClass,PubliclyAccessible,BackupRetentionPeriod]" \
      --output table
  fi
  echo "S3 buckets named ${NAME_PREFIX}-*:"
  aws s3api list-buckets --query "Buckets[?starts_with(Name, '${NAME_PREFIX}-')].[Name,CreationDate]" --output table
  if [[ "${SCOPE}" == "full" ]]; then
    echo "Security groups tagged ${TAG_KEY}=${TAG_VALUE}:"
    aws ec2 describe-security-groups --filters "Name=tag:${TAG_KEY},Values=${TAG_VALUE}" \
      --query 'SecurityGroups[].[GroupId,GroupName]' --output table
    echo "Everything the tagging API finds with ${TAG_KEY}=${TAG_VALUE}:"
  else
    echo "Buckets among them that carry ${TAG_KEY}=${TAG_VALUE}:"
  fi
  find_tagged
  printf '  %s\n' "${TAGGED[@]+"${TAGGED[@]}"}"
}

cmd_destroy() {
  require_safe_environment
  show_identity
  find_tagged
  [[ ${#TAGGED[@]} -gt 0 ]] || die "no resource tagged ${TAG_KEY}=${TAG_VALUE} exists in ${REGION} (scope ${SCOPE}): nothing to destroy."
  echo "Tagged resources found:"
  printf '  %s\n' "${TAGGED[@]}"
  require_tfvars
  tf init -input=false >/dev/null
  tf_scoped plan -destroy -input=false
  confirm_region "DELETE everything the plan above lists (Terraform only deletes what is in its own state)"
  tf_scoped destroy -input=false -auto-approve
  echo
  echo "Checking that nothing is left..."
  if ! report_clean; then
    echo "Delete the leftovers by hand in the console (demo/aws/README.md, 'Check that nothing is left')." >&2
  fi
}

# Prints the verdict; returns 1 when something is left.
report_clean() {
  find_leftovers
  if [[ ${#LEFT[@]} -gt 0 ]]; then
    echo "NOT CLEAN. Still present:"
    printf '  %s\n' "${LEFT[@]}"
    return 1
  fi
  if [[ "${SCOPE}" == "full" ]]; then
    echo "Clean: nothing tagged ${TAG_KEY}=${TAG_VALUE} and no ${NAME_PREFIX} database, snapshot, bucket or security group."
  else
    echo "Clean: nothing tagged ${TAG_KEY}=${TAG_VALUE} and no ${NAME_PREFIX}-* bucket (S3 scope: EC2 and RDS are not checked)."
  fi
}

cmd_check_clean() {
  require_safe_environment
  show_identity
  report_clean
}

main() {
  local command="${1:-}"
  case "${command}" in
    plan) cmd_plan ;;
    apply) cmd_apply ;;
    destroy) cmd_destroy ;;
    status) cmd_status ;;
    check-clean) cmd_check_clean ;;
    -h | --help | help) usage 0 ;;
    *) usage 1 ;;
  esac
}

main "$@"
