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
    (demo / "terraform.tfvars").write_text('my_ip_cidr = "198.51.100.9/32"\n')
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
    result = sandbox("status", AWS_REGION="us-east-1")
    assert result.returncode != 0
    assert "ap-south-1" in result.stderr


def test_refuses_the_example_ip(sandbox) -> None:
    (sandbox.demo / "terraform.tfvars").write_text('my_ip_cidr = "203.0.113.7/32"\n')
    result = sandbox("plan")
    assert result.returncode != 0
    assert "example IP" in result.stderr


def test_apply_needs_the_region_typed(sandbox) -> None:
    result = sandbox("apply", stdin="yes\n")
    assert result.returncode != 0
    assert "not confirmed" in result.stderr
    assert "terraform -chdir" in sandbox.calls() and " apply " not in sandbox.calls()


def test_apply_with_the_region_typed_runs_and_deletes_the_plan_file(sandbox) -> None:
    result = sandbox("apply", stdin="ap-south-1\n")
    assert result.returncode == 0, result.stderr
    assert " apply " in sandbox.calls()
    assert not list(sandbox.demo.glob("*.plan"))


def test_destroy_refuses_when_nothing_is_tagged(sandbox) -> None:
    result = sandbox("destroy", stdin="ap-south-1\n")
    assert result.returncode != 0
    assert "nothing to destroy" in result.stderr
    assert "destroy" not in sandbox.calls().replace("plan -destroy", "")


def test_destroy_needs_the_region_typed(sandbox) -> None:
    arn = "arn:aws:s3:::driftpilot-demo-abcd1234"
    result = sandbox("destroy", stdin="nope\n", STUB_TAGGED=arn)
    assert result.returncode != 0
    assert "not confirmed" in result.stderr
    assert "destroy -input=false -auto-approve" not in sandbox.calls()


def test_destroy_runs_after_confirmation(sandbox) -> None:
    arn = "arn:aws:s3:::driftpilot-demo-abcd1234"
    result = sandbox("destroy", stdin="ap-south-1\n", STUB_TAGGED=arn)
    assert "destroy -input=false -auto-approve" in sandbox.calls()
    assert "NOT CLEAN" in result.stdout  # the stand-in `aws` still lists the tagged resource


def test_check_clean_passes_on_an_empty_account(sandbox) -> None:
    result = sandbox("check-clean")
    assert result.returncode == 0, result.stderr
    assert "Clean" in result.stdout


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("STUB_TAGGED", "arn:aws:s3:::driftpilot-demo-abcd1234"),
        ("STUB_RDS", "driftpilot-demo-db"),
        ("STUB_SNAPSHOTS", "snap-0123456789abcdef0"),
    ],
)
def test_check_clean_fails_when_something_is_left(sandbox, variable, value) -> None:
    result = sandbox("check-clean", **{variable: value})
    assert result.returncode == 1
    assert "NOT CLEAN" in result.stdout and value in result.stdout


def test_check_clean_fails_closed_when_aws_cannot_be_read(sandbox) -> None:
    result = sandbox("check-clean", STUB_FAIL_ON="describe-db-snapshots")
    assert result.returncode != 0
    assert "Clean" not in result.stdout


def test_script_never_prints_the_password(sandbox) -> None:
    text = SCRIPT.read_text()
    assert "db_password" not in text and "-raw" not in text
    assert os.access(SCRIPT, os.X_OK)
