"""scripts/aws_demo.sh with stand-in `aws` and `terraform` programs (no real AWS or Terraform)."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "aws_demo.sh"

AWS_STUB = """#!/usr/bin/env bash
echo "aws $*" >> "$STUB_LOG"
[[ -n "${STUB_FAIL_ON:-}" && "$*" == *"$STUB_FAIL_ON"* ]] && exit 255
case "$*" in
  *"get-caller-identity"*"Account"*) echo "123456789012" ;;
  *"get-caller-identity"*) echo "arn:aws:iam::123456789012:user/demo-operator" ;;
  *resourcegroupstaggingapi*) echo -e "${STUB_TAGGED:-}" ;;
  *"s3api list-buckets"*) echo -e "${STUB_BUCKETS:-}" ;;
  *"s3api get-bucket-tagging"*) echo "${STUB_BUCKET_TAG:-}" ;;
  *"rds describe-db-instances"*) echo "${STUB_RDS:-}" ;;
  *"ec2 describe-snapshots"*) echo "${STUB_SNAPSHOTS:-}" ;;
  *) echo "" ;;
esac
"""

TERRAFORM_STUB = """#!/usr/bin/env bash
echo "terraform $*" >> "$STUB_LOG"
for arg in "$@"; do
  case "$arg" in -out=*) touch "${arg#-out=}" ;; esac
done
exit 0
"""


@pytest.fixture
def sandbox(tmp_path):
    """A copy of the script next to a fake demo/aws folder, plus stubs first on PATH."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / "aws_demo.sh")
    demo = tmp_path / "demo" / "aws"
    demo.mkdir(parents=True)
    (demo / "terraform.tfvars").write_text(
        'my_ip_cidr = "198.51.100.9/32"\n'
    )  # the "s3" scope (the default) ignores it
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("aws", AWS_STUB), ("terraform", TERRAFORM_STUB)):
        path = bin_dir / name
        path.write_text(body)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "STUB_LOG": str(log),
        "AWS_PROFILE": "driftpilot-demo",
    }

    def run(*args: str, stdin: str = "", **extra: str) -> subprocess.CompletedProcess:
        merged = {**env, **extra}
        merged = {k: v for k, v in merged.items() if v != "__unset__"}
        return subprocess.run(
            ["bash", str(tmp_path / "scripts" / "aws_demo.sh"), *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=merged,
            timeout=30,
        )

    run.calls = lambda: log.read_text()
    run.demo = demo
    return run


def test_refuses_without_a_profile(sandbox) -> None:
    result = sandbox("plan", AWS_PROFILE="__unset__")
    assert result.returncode != 0
    assert "AWS_PROFILE is not set" in result.stderr
    assert sandbox.calls() == ""


def test_refuses_keys_in_the_environment(sandbox) -> None:
    result = sandbox("status", AWS_ACCESS_KEY_ID="AKIAFAKE")
    assert result.returncode != 0
    assert "profile" in result.stderr
    assert sandbox.calls() == ""


def test_refuses_another_region(sandbox) -> None:
    result = sandbox("status", AWS_REGION="ap-south-1")  # the default s3 scope runs in us-east-1
    assert result.returncode != 0
    assert "us-east-1" in result.stderr
    result = sandbox("status", AWS_DEFAULT_REGION="eu-west-1")
    assert result.returncode != 0 and "us-east-1" in result.stderr
    assert sandbox.calls() == ""


def test_full_scope_refuses_other_regions_too(sandbox) -> None:
    result = sandbox("status", DEMO_SCOPE="full", AWS_REGION="us-east-1")
    assert result.returncode != 0
    assert "ap-south-1" in result.stderr


def test_refuses_an_unknown_scope(sandbox) -> None:
    result = sandbox("status", DEMO_SCOPE="everything")
    assert result.returncode != 0
    assert "unknown demo scope" in result.stderr
    assert sandbox.calls() == ""


def test_scope_can_come_from_terraform_tfvars(sandbox) -> None:
    (sandbox.demo / "terraform.tfvars").write_text(
        'demo_scope = "full"\nmy_ip_cidr = "198.51.100.9/32"\n'
    )
    result = sandbox("status", AWS_REGION="us-east-1")
    assert result.returncode != 0 and "ap-south-1" in result.stderr
    assert "Scope: full" in sandbox("status").stdout


def test_full_scope_refuses_the_example_ip(sandbox) -> None:
    (sandbox.demo / "terraform.tfvars").write_text('my_ip_cidr = "203.0.113.7/32"\n')
    result = sandbox("plan", DEMO_SCOPE="full")
    assert result.returncode != 0
    assert "example IP" in result.stderr


def test_s3_scope_needs_no_tfvars_and_passes_its_scope_to_terraform(sandbox) -> None:
    (sandbox.demo / "terraform.tfvars").unlink()
    result = sandbox("plan")
    assert result.returncode == 0, result.stderr
    assert "Scope: s3" in result.stdout and "Region: us-east-1" in result.stdout
    assert "plan -var demo_scope=s3 -input=false" in sandbox.calls()


def test_apply_needs_the_region_typed(sandbox) -> None:
    result = sandbox("apply", stdin="yes\n")
    assert result.returncode != 0
    assert "not confirmed" in result.stderr
    assert "terraform -chdir" in sandbox.calls() and " apply " not in sandbox.calls()
    assert "type the region name (us-east-1)" in result.stdout


def test_apply_with_the_region_typed_runs_and_deletes_the_plan_file(sandbox) -> None:
    result = sandbox("apply", stdin="us-east-1\n")
    assert result.returncode == 0, result.stderr
    assert " apply " in sandbox.calls()
    assert not list(sandbox.demo.glob("*.plan"))
    assert "ap-south-1" not in result.stdout


def test_apply_in_the_full_scope_needs_ap_south_1(sandbox) -> None:
    refused = sandbox("apply", DEMO_SCOPE="full", stdin="us-east-1\n")
    assert refused.returncode != 0 and "not confirmed" in refused.stderr
    assert " apply " not in sandbox.calls()
    result = sandbox("apply", DEMO_SCOPE="full", stdin="ap-south-1\n")
    assert result.returncode == 0, result.stderr
    assert "demo_scope=full" in sandbox.calls() and " apply " in sandbox.calls()


def test_destroy_refuses_when_nothing_is_tagged(sandbox) -> None:
    result = sandbox("destroy", stdin="us-east-1\n")
    assert result.returncode != 0
    assert "nothing to destroy" in result.stderr
    assert "destroy" not in sandbox.calls().replace("plan -var demo_scope=s3 -destroy", "")


def test_destroy_ignores_a_bucket_that_is_not_tagged(sandbox) -> None:
    result = sandbox("destroy", stdin="us-east-1\n", STUB_BUCKETS="driftpilot-demo-abcd1234")
    assert result.returncode != 0 and "nothing to destroy" in result.stderr


BUCKET = {"STUB_BUCKETS": "driftpilot-demo-abcd1234", "STUB_BUCKET_TAG": "driftpilot"}


def test_destroy_needs_the_region_typed(sandbox) -> None:
    result = sandbox("destroy", stdin="ap-south-1\n", **BUCKET)
    assert result.returncode != 0
    assert "not confirmed" in result.stderr
    assert "destroy -var demo_scope=s3 -input=false -auto-approve" not in sandbox.calls()


def test_destroy_runs_after_confirmation(sandbox) -> None:
    result = sandbox("destroy", stdin="us-east-1\n", **BUCKET)
    assert "destroy -var demo_scope=s3 -input=false -auto-approve" in sandbox.calls()
    assert "NOT CLEAN" in result.stdout  # the stand-in `aws` still lists the bucket


def test_full_destroy_uses_the_tagging_api(sandbox) -> None:
    arn = "arn:aws:s3:::driftpilot-demo-abcd1234"
    result = sandbox("destroy", DEMO_SCOPE="full", stdin="ap-south-1\n", STUB_TAGGED=arn)
    assert "destroy -var demo_scope=full -input=false -auto-approve" in sandbox.calls()
    assert "NOT CLEAN" in result.stdout


def test_check_clean_passes_on_an_empty_account(sandbox) -> None:
    result = sandbox("check-clean")
    assert result.returncode == 0, result.stderr
    assert "Clean" in result.stdout


def test_s3_scope_never_calls_ec2_rds_budgets_or_the_tagging_api(sandbox) -> None:
    for command in ("status", "check-clean", "plan"):
        assert sandbox(command, **BUCKET).returncode in (0, 1)
    calls = sandbox.calls()
    assert "s3api list-buckets" in calls
    for banned in ("ec2", "rds", "budgets", "resourcegroupstaggingapi"):
        assert f"aws {banned}" not in calls, banned


def test_s3_check_clean_fails_when_a_bucket_is_left(sandbox) -> None:
    result = sandbox("check-clean", **BUCKET)
    assert result.returncode == 1
    assert "NOT CLEAN" in result.stdout and "driftpilot-demo-abcd1234" in result.stdout
    untagged = sandbox("check-clean", STUB_BUCKETS="driftpilot-demo-abcd1234")
    assert untagged.returncode == 1  # still listed by name even when the tag cannot be read


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("STUB_TAGGED", "arn:aws:s3:::driftpilot-demo-abcd1234"),
        ("STUB_RDS", "driftpilot-demo-db"),
        ("STUB_SNAPSHOTS", "snap-0123456789abcdef0"),
    ],
)
def test_full_check_clean_fails_when_something_is_left(sandbox, variable, value) -> None:
    result = sandbox("check-clean", DEMO_SCOPE="full", **{variable: value})
    assert result.returncode == 1
    assert "NOT CLEAN" in result.stdout and value in result.stdout


def test_check_clean_fails_closed_when_aws_cannot_be_read(sandbox) -> None:
    result = sandbox("check-clean", DEMO_SCOPE="full", STUB_FAIL_ON="describe-db-snapshots")
    assert result.returncode != 0
    assert "Clean" not in result.stdout
    result = sandbox("check-clean", STUB_FAIL_ON="list-buckets")  # s3 scope: the bucket list
    assert result.returncode != 0
    assert "Clean" not in result.stdout


def test_script_never_prints_the_password(sandbox) -> None:
    text = SCRIPT.read_text()
    assert "db_password" not in text and "-raw" not in text
    assert os.access(SCRIPT, os.X_OK)
