#!/usr/bin/env bash
# Safe wrapper around the real-Azure demo in demo/azure (Terraform + the Azure CLI).
#
#   scripts/azure_demo.sh plan         # show what would be created (changes nothing)
#   scripts/azure_demo.sh apply        # create it (asks you to type the location)
#   scripts/azure_demo.sh status       # list the demo resource groups and what is in them
#   scripts/azure_demo.sh destroy      # delete it all (asks you to type the location)
#   scripts/azure_demo.sh check-clean  # exit 1 if a demo resource group (rg-driftpilot-demo-*) is left
#
# You must be logged in first:  az login   (a browser window opens; use the student account).
# The demo is one resource group with a storage account and a network security group in it. The location comes from
# DEMO_LOCATION, else `location = "..."` in demo/azure/terraform.tfvars, else centralindia. `apply` and `destroy` print
# the subscription and the location and wait for you to type the location name.
set -euo pipefail

LOCATION=""    # set by resolve_location
SUB_NAME=""    # set by show_identity
SUB_ID=""      # set by show_identity
RG_PREFIX="rg-driftpilot-demo-"
STORAGE_PREFIX="dpdemo"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEMO_DIR="${HERE}/../demo/azure"
PLAN_FILE="${DEMO_DIR}/.demo.plan" # gitignored (*.plan), deleted after use

die() {
  echo "error: $*" >&2
  exit 1
}

usage() {
  sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit "${1:-1}"
}

# The location comes from DEMO_LOCATION, else from `location = "..."` in terraform.tfvars, else centralindia.
resolve_location() {
  local file="${DEMO_DIR}/terraform.tfvars"
  LOCATION="${DEMO_LOCATION:-}"
  if [[ -z "${LOCATION}" && -f "${file}" ]]; then
    LOCATION="$(sed -n 's/^[[:space:]]*location[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "${file}" | tail -n 1)"
  fi
  LOCATION="${LOCATION:-centralindia}"
  [[ "${LOCATION}" =~ ^[a-z0-9]+$ ]] || die "location '${LOCATION}' must be a short lowercase region name such as centralindia (see 'az account list-locations -o table')."
}

require_safe_environment() {
  resolve_location
  # Only your own `az login` session is used: no passwords, secrets or keys from the environment.
  if [[ -n "${ARM_CLIENT_SECRET:-}" || -n "${ARM_CLIENT_CERTIFICATE_PATH:-}" || -n "${ARM_ACCESS_KEY:-}" || -n "${ARM_OIDC_TOKEN:-}" ]]; then
    die "Azure secrets are set in the environment (ARM_CLIENT_SECRET, ARM_CLIENT_CERTIFICATE_PATH, ARM_ACCESS_KEY or ARM_OIDC_TOKEN). Unset them and use 'az login'."
  fi
  command -v az >/dev/null || die "the Azure CLI is not installed (see demo/azure/README.md, 'Before you start')"
  command -v terraform >/dev/null || die "terraform is not installed"
}

# Needs a login. Prints the subscription and the location, and makes Terraform use that same subscription.
show_identity() {
  local line
  line="$(az account show --query '[name, id]' --output tsv)" || die "not logged in to Azure. Run:  az login"
  SUB_NAME="${line%%$'\t'*}"
  SUB_ID="${line##*$'\t'}"
  [[ -n "${SUB_ID}" && "${SUB_ID}" != "${line}" ]] || die "could not read the subscription from 'az account show'. Run:  az login"
  if [[ -n "${ARM_SUBSCRIPTION_ID:-}" && "${ARM_SUBSCRIPTION_ID}" != "${SUB_ID}" ]]; then
    die "ARM_SUBSCRIPTION_ID (${ARM_SUBSCRIPTION_ID}) is not the subscription 'az login' is using (${SUB_ID}). Unset it."
  fi
  export ARM_SUBSCRIPTION_ID="${SUB_ID}"
  echo "Subscription: ${SUB_NAME} (${SUB_ID})"
  echo "Location: ${LOCATION}"
}

# terraform.tfvars must hold your own IP (the firewall rule allows SSH from that address only).
require_tfvars() {
  [[ -f "${DEMO_DIR}/terraform.tfvars" ]] || die "demo/azure/terraform.tfvars is missing. Copy terraform.tfvars.example to terraform.tfvars and put your IP in it."
  if grep -Eq '^[[:space:]]*my_ip_cidr[[:space:]]*=[[:space:]]*"203\.0\.113\.7/32"' "${DEMO_DIR}/terraform.tfvars"; then
    die "terraform.tfvars still has the example IP (203.0.113.7/32). Put your own address there."
  fi
}

tf() {
  terraform -chdir="${DEMO_DIR}" "$@"
}

# plan/apply/destroy always get the location from here, so the script and Terraform cannot disagree.
tf_scoped() {
  local sub="$1"
  shift
  tf "${sub}" -var "location=${LOCATION}" "$@"
}

confirm_location() {
  local what="$1" answer
  echo
  echo "This will ${what}."
  echo "It should cost almost nothing (no virtual machine, no database), but destroy the demo when you are done."
  printf 'To continue, type the location name (%s): ' "${LOCATION}"
  read -r answer || answer=""
  [[ "${answer}" == "${LOCATION}" ]] || die "not confirmed, nothing was changed."
}

# Everything below fills the global arrays instead of printing from a subshell, so that a failed Azure call
# stops the whole script: a check that cannot see Azure must never report "clean".
GROUPS_FOUND=()
LEFT=()

# Runs one read-only Azure CLI query and returns its items, one per line, in QUERY_RESULT.
QUERY_RESULT=""
query() {
  local what="$1" out
  shift
  out="$(az "$@" --output tsv)" || die "the Azure call for '${what}' failed, so I cannot tell what exists"
  QUERY_RESULT="$(sed '/^$/d; /^None$/d' <<<"${out}")"
}

# Adds the last query's items to LEFT with a label.
add_left() {
  local label="$1" line
  while IFS= read -r line; do
    [[ -z "${line}" ]] || LEFT+=("${label}: ${line}")
  done <<<"${QUERY_RESULT}"
}

# Fills GROUPS_FOUND with the resource groups named rg-driftpilot-demo-* or tagged demo=driftpilot.
find_groups() {
  local line
  GROUPS_FOUND=()
  query "resource groups" group list \
    --query "[?starts_with(name, '${RG_PREFIX}') || tags.demo == 'driftpilot'].name"
  while IFS= read -r line; do
    [[ -z "${line}" ]] || GROUPS_FOUND+=("${line}")
  done <<<"${QUERY_RESULT}"
}

# Fills LEFT with one line per leftover; empty means the subscription is clean.
find_leftovers() {
  local group
  LEFT=()
  find_groups
  for group in "${GROUPS_FOUND[@]+"${GROUPS_FOUND[@]}"}"; do
    LEFT+=("resource group: ${group}")
    query "resources in ${group}" resource list --resource-group "${group}" --query "[].id"
    add_left "  inside ${group}"
  done
  # A storage account of the demo that sits outside the group (someone moved it) would still be there.
  query "storage accounts" storage account list --query "[?starts_with(name, '${STORAGE_PREFIX}')].id"
  add_left "storage account"
}

# Prints the verdict; returns 1 when something is left.
report_clean() {
  find_leftovers
  if [[ ${#LEFT[@]} -gt 0 ]]; then
    echo "NOT CLEAN. Still present:"
    printf '  %s\n' "${LEFT[@]}"
    return 1
  fi
  echo "Clean: no resource group ${RG_PREFIX}* (or tagged demo=driftpilot) and no ${STORAGE_PREFIX}* storage account in this subscription."
}

# Read-only: are the two services the demo needs registered on this subscription?
show_registration() {
  local namespace state
  for namespace in Microsoft.Storage Microsoft.Network; do
    state="$(az provider show --namespace "${namespace}" --query registrationState --output tsv 2>/dev/null)" || state="unknown"
    echo "Service ${namespace}: ${state:-unknown}"
    if [[ "${state}" != "Registered" ]]; then
      echo "  note: if apply says the service is not registered, run:  az provider register --namespace ${namespace}" >&2
    fi
  done
}

cmd_plan() {
  require_safe_environment
  show_identity
  require_tfvars
  show_registration
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
  confirm_location "CREATE the resources above in the Azure subscription '${SUB_NAME}' (a resource group, a storage account and a network security group)"
  tf apply -input=false "${PLAN_FILE}"
  echo
  echo "Done. Next steps: demo/azure/RUNBOOK.md. When finished: scripts/azure_demo.sh destroy"
}

cmd_status() {
  local group
  require_safe_environment
  show_identity
  echo
  find_groups
  if [[ ${#GROUPS_FOUND[@]} -eq 0 ]]; then
    echo "No resource group named ${RG_PREFIX}* (or tagged demo=driftpilot)."
  fi
  for group in "${GROUPS_FOUND[@]+"${GROUPS_FOUND[@]}"}"; do
    echo "Resource group ${group}:"
    az resource list --resource-group "${group}" --query "[].[name,type,location]" --output table
  done
}

cmd_destroy() {
  require_safe_environment
  show_identity
  find_groups
  [[ ${#GROUPS_FOUND[@]} -gt 0 ]] || die "no resource group ${RG_PREFIX}* exists in this subscription: nothing to destroy."
  echo "Demo resource groups found:"
  printf '  %s\n' "${GROUPS_FOUND[@]}"
  require_tfvars
  tf init -input=false >/dev/null
  tf_scoped plan -destroy -input=false
  confirm_location "DELETE everything the plan above lists (Terraform only deletes what is in its own state)"
  tf_scoped destroy -input=false -auto-approve
  echo
  echo "Checking that nothing is left..."
  report_clean || {
    echo "Delete the leftovers by hand in the portal (demo/azure/README.md, 'Check that nothing is left')." >&2
    exit 1
  }
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
