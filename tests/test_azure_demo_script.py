"""scripts/azure_demo.sh with stand-in `az` and `terraform` (no real Azure or Terraform)."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "azure_demo.sh"
SUB_ID = "11111111-2222-3333-4444-555555555555"

AZ_STUB = """#!/usr/bin/env bash
echo "az $*" >> "$STUB_LOG"
[[ -n "${STUB_FAIL_ON:-}" && "$*" == *"$STUB_FAIL_ON"* ]] && exit 1
case "$*" in
  *"account show"*)
    [[ -n "${STUB_NOT_LOGGED_IN:-}" ]] && { echo "Please run 'az login'" >&2; exit 1; }
    printf 'Azure for Students\\t%s\\n' "${STUB_SUB_ID:-11111111-2222-3333-4444-555555555555}" ;;
  *"provider show"*) echo "${STUB_PROVIDER_STATE:-Registered}" ;;
  *"group list"*) echo -e "${STUB_GROUPS:-}" ;;
  *"resource list"*) echo -e "${STUB_RESOURCES:-}" ;;
  *"storage account list"*) echo -e "${STUB_STORAGE:-}" ;;
  *) echo "" ;;
esac
"""

TERRAFORM_STUB = """#!/usr/bin/env bash
echo "terraform $* [ARM_SUBSCRIPTION_ID=${ARM_SUBSCRIPTION_ID:-}]" >> "$STUB_LOG"
for arg in "$@"; do
  case "$arg" in -out=*) touch "${arg#-out=}" ;; esac
done
exit 0
"""

GROUP = {"STUB_GROUPS": "rg-driftpilot-demo-a1b2c3d4"}


@pytest.fixture
def sandbox(tmp_path):
    """A copy of the script next to a fake demo/azure folder, plus stubs first on PATH."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "azure_demo.sh")
    demo = tmp_path / "demo" / "azure"
    demo.mkdir(parents=True)
    (demo / "terraform.tfvars").write_text('my_ip_cidr = "198.51.100.9/32"\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("az", AZ_STUB), ("terraform", TERRAFORM_STUB)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "STUB_LOG": str(log)}

    def run(*args: str, stdin: str = "", **extra: str) -> subprocess.CompletedProcess:
        merged = {k: v for k, v in {**env, **extra}.items() if v != "__unset__"}
        return subprocess.run(
            ["bash", str(tmp_path / "scripts" / "azure_demo.sh"), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=merged,
            timeout=30,
        )

    run.calls = lambda: log.read_text()
    run.demo = demo
    return run


def test_refuses_when_not_logged_in(sandbox) -> None:
    result = sandbox("plan", STUB_NOT_LOGGED_IN="1")
    assert result.returncode != 0
    assert "az login" in result.stderr
    assert "terraform" not in sandbox.calls()


@pytest.mark.parametrize(
    "name", ["ARM_CLIENT_SECRET", "ARM_CLIENT_CERTIFICATE_PATH", "ARM_ACCESS_KEY"]
)
def test_refuses_secrets_in_the_environment(sandbox, name: str) -> None:
    result = sandbox("status", **{name: "x"})
    assert result.returncode != 0
    assert "az login" in result.stderr
    assert sandbox.calls() == ""


def test_refuses_another_subscription_in_the_environment(sandbox) -> None:
    result = sandbox("plan", ARM_SUBSCRIPTION_ID="99999999-2222-3333-4444-555555555555")
    assert result.returncode != 0 and "ARM_SUBSCRIPTION_ID" in result.stderr
    assert "terraform" not in sandbox.calls()


def test_refuses_a_malformed_location(sandbox) -> None:
    result = sandbox("plan", DEMO_LOCATION="Central India")
    assert result.returncode != 0 and "lowercase region name" in result.stderr
    assert sandbox.calls() == ""


def test_shows_subscription_and_location_and_passes_both_to_terraform(sandbox) -> None:
    result = sandbox("plan")
    assert result.returncode == 0, result.stderr
    assert f"Subscription: Azure for Students ({SUB_ID})" in result.stdout
    assert "Location: centralindia" in result.stdout
    assert f"plan -var location=centralindia -input=false [ARM_SUBSCRIPTION_ID={SUB_ID}]" in (
        sandbox.calls()
    )


def test_location_can_come_from_terraform_tfvars_or_the_environment(sandbox) -> None:
    (sandbox.demo / "terraform.tfvars").write_text(
        'my_ip_cidr = "198.51.100.9/32"\nlocation = "southeastasia"\n'
    )
    assert "Location: southeastasia" in sandbox("status").stdout
    assert "Location: uaenorth" in sandbox("status", DEMO_LOCATION="uaenorth").stdout


def test_plan_warns_when_a_service_is_not_registered(sandbox) -> None:
    result = sandbox("plan", STUB_PROVIDER_STATE="NotRegistered")
    assert result.returncode == 0
    assert "az provider register --namespace Microsoft.Storage" in result.stderr


def test_plan_refuses_the_example_ip(sandbox) -> None:
    (sandbox.demo / "terraform.tfvars").write_text('my_ip_cidr = "203.0.113.7/32"\n')
    result = sandbox("plan")
    assert result.returncode != 0 and "example IP" in result.stderr
    assert "terraform" not in sandbox.calls()


def test_plan_needs_a_tfvars_file(sandbox) -> None:
    (sandbox.demo / "terraform.tfvars").unlink()
    result = sandbox("plan")
    assert result.returncode != 0 and "terraform.tfvars is missing" in result.stderr


def test_apply_needs_the_location_typed(sandbox) -> None:
    result = sandbox("apply", stdin="yes\n")
    assert result.returncode != 0
    assert "not confirmed" in result.stderr
    assert "type the location name (centralindia)" in result.stdout
    assert " apply " not in sandbox.calls()
    assert not list(sandbox.demo.glob("*.plan"))


def test_apply_with_the_location_typed_runs_and_deletes_the_plan_file(sandbox) -> None:
    result = sandbox("apply", stdin="centralindia\n")
    assert result.returncode == 0, result.stderr
    assert " apply " in sandbox.calls()
    assert not list(sandbox.demo.glob("*.plan"))


def test_apply_confirms_the_other_location_when_one_is_chosen(sandbox) -> None:
    refused = sandbox("apply", DEMO_LOCATION="uaenorth", stdin="centralindia\n")
    assert refused.returncode != 0 and "not confirmed" in refused.stderr
    assert " apply " not in sandbox.calls()
    ok = sandbox("apply", DEMO_LOCATION="uaenorth", stdin="uaenorth\n")
    assert ok.returncode == 0, ok.stderr
    assert "-var location=uaenorth" in sandbox.calls()


def test_destroy_refuses_when_there_is_no_demo_group(sandbox) -> None:
    result = sandbox("destroy", stdin="centralindia\n")
    assert result.returncode != 0 and "nothing to destroy" in result.stderr
    assert "-destroy" not in sandbox.calls()


def test_destroy_needs_the_location_typed(sandbox) -> None:
    result = sandbox("destroy", stdin="uaenorth\n", **GROUP)
    assert result.returncode != 0 and "not confirmed" in result.stderr
    assert "destroy -var location=centralindia -input=false -auto-approve" not in sandbox.calls()


def test_destroy_runs_after_confirmation_and_reports_what_is_left(sandbox) -> None:
    result = sandbox("destroy", stdin="centralindia\n", **GROUP)
    assert "destroy -var location=centralindia -input=false -auto-approve" in sandbox.calls()
    assert "NOT CLEAN" in result.stdout  # the stand-in `az` still lists the group
    assert result.returncode == 1


def test_check_clean_passes_on_an_empty_subscription(sandbox) -> None:
    result = sandbox("check-clean")
    assert result.returncode == 0, result.stderr
    assert "Clean" in result.stdout


def test_check_clean_lists_a_left_group_and_what_is_inside(sandbox) -> None:
    result = sandbox(
        "check-clean", STUB_RESOURCES="/subscriptions/x/storageAccounts/dpdemoa1b2c3d4", **GROUP
    )
    assert result.returncode == 1
    assert "NOT CLEAN" in result.stdout
    assert "resource group: rg-driftpilot-demo-a1b2c3d4" in result.stdout
    assert "dpdemoa1b2c3d4" in result.stdout


def test_check_clean_finds_a_group_by_name_or_demo_tag_in_one_query(sandbox) -> None:
    sandbox("check-clean")
    group_calls = [c for c in sandbox.calls().splitlines() if "group list" in c]
    assert len(group_calls) == 1
    assert "starts_with(name, 'rg-driftpilot-demo-')" in group_calls[0]
    assert "tags.demo == 'driftpilot'" in group_calls[0]


def test_check_clean_fails_when_a_demo_storage_account_is_left_outside_the_group(sandbox) -> None:
    result = sandbox("check-clean", STUB_STORAGE="/subscriptions/x/storageAccounts/dpdemoa1b2c3d4")
    assert result.returncode == 1 and "storage account" in result.stdout


@pytest.mark.parametrize("failing", ["group list", "resource list", "storage account list"])
def test_check_clean_fails_closed_when_azure_cannot_be_read(sandbox, failing: str) -> None:
    result = sandbox("check-clean", STUB_FAIL_ON=failing, **GROUP)
    assert result.returncode != 0
    assert "Clean" not in result.stdout
    assert "cannot tell what exists" in result.stderr


def test_status_lists_the_group_contents(sandbox) -> None:
    result = sandbox("status", **GROUP)
    assert result.returncode == 0, result.stderr
    assert "Resource group rg-driftpilot-demo-a1b2c3d4" in result.stdout
    assert "az resource list --resource-group rg-driftpilot-demo-a1b2c3d4" in sandbox.calls()


def test_script_only_reads_with_az_and_is_executable(sandbox) -> None:
    text = SCRIPT.read_text()
    for verb in (
        "az group delete",
        "az group create",
        "az resource delete",
        "az storage account update",
    ):
        assert verb not in text
    assert "get-access-token" not in text and "list-keys" not in text
    assert os.access(SCRIPT, os.X_OK)
    sandbox("check-clean", **GROUP)
    for call in sandbox.calls().splitlines():
        if call.startswith("az "):
            assert any(w in call for w in (" show", " list")), call
