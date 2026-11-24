"""Static checks on demo/aws: the cost and safety rules hold in the files (nothing is run)."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "demo" / "aws"
MAIN = (DEMO / "main.tf").read_text()
VARIABLES = (DEMO / "variables.tf").read_text()
POLICIES = ["iam-policy-demo-operator.json", "iam-policy-driftpilot-readonly.json"]
WRITE_VERBS = ("Create", "Delete", "Put", "Modify", "Authorize", "Revoke", "Add", "Remove", "Tag")


def test_no_resource_that_bills_on_its_own() -> None:
    types = set(re.findall(r'^resource "(\w+)"', MAIN, flags=re.M))
    banned = {
        "aws_nat_gateway", "aws_eip", "aws_lb", "aws_alb", "aws_instance", "aws_cloudtrail",
        "aws_secretsmanager_secret", "aws_db_instance_automated_backups_replication",
        "aws_flow_log", "aws_kms_key", "aws_cloudwatch_log_group",
    }  # fmt: skip
    assert not types & banned
    assert types == {
        "random_id", "random_password", "aws_s3_bucket", "aws_s3_bucket_public_access_block",
        "aws_s3_bucket_versioning", "aws_s3_bucket_server_side_encryption_configuration",
        "aws_security_group", "aws_db_instance", "aws_budgets_budget",
    }  # fmt: skip


def test_database_settings_are_the_cheap_and_clean_up_friendly_ones() -> None:
    for line in (
        "instance_class = var.db_instance_class",
        "allocated_storage = 20",
        'storage_type      = "gp3"',
        "multi_az               = false",
        "skip_final_snapshot          = true",
        "deletion_protection          = false",
        "backup_retention_period      = 1",
        "performance_insights_enabled = false",
        "monitoring_interval          = 0",
        "storage_encrypted = true",
    ):
        assert line in MAIN, line
    assert 'default     = "db.t4g.micro"' in VARIABLES


def test_every_resource_that_can_be_tagged_is_tagged_with_the_demo_tag() -> None:
    assert 'demo = "driftpilot"' in MAIN and 'team = "platform"' in MAIN
    for kind in ("aws_s3_bucket", "aws_security_group", "aws_db_instance", "aws_budgets_budget"):
        block = re.search(rf'resource "{kind}" "\w+" \{{(.*?)\n\}}\n', MAIN, flags=re.S)
        assert block and "tags" in block.group(1) and "local.tags" in block.group(1), kind


def test_the_security_group_cannot_be_opened_to_the_world_by_the_variable() -> None:
    variables = (DEMO / "variables.tf").read_text()
    assert 'var.my_ip_cidr != "0.0.0.0/0"' in variables
    assert 'endswith(var.my_ip_cidr, "/32")' in variables
    assert "0.0.0.0/0" not in MAIN  # the only mention is the variable's rejection message


def test_only_the_bucket_is_created_without_a_count_guard() -> None:
    """The "s3" scope must create the bucket resources only; everything else is full-scope only."""
    always = {
        "random_id", "aws_s3_bucket", "aws_s3_bucket_public_access_block",
        "aws_s3_bucket_versioning", "aws_s3_bucket_server_side_encryption_configuration",
    }  # fmt: skip
    guarded = {
        "aws_security_group": "local.full ? 1 : 0",
        "aws_db_instance": "local.full ? 1 : 0",
        "random_password": "local.full ? 1 : 0",
        "aws_budgets_budget": "local.full && var.enable_budget_guard ? 1 : 0",
    }
    for kind in re.findall(r'^resource "(\w+)"', MAIN, flags=re.M):
        if kind in always:
            continue
        block = re.search(rf'resource "{kind}" "\w+" \{{(.*?)\n\}}\n', MAIN, flags=re.S).group(1)
        assert f"count = {guarded[kind]}" in block, kind
    vpc = re.search(r'data "aws_vpc" "default" \{(.*?)\n\}\n', MAIN, flags=re.S).group(1)
    assert "count = local.full ? 1 : 0" in vpc
    assert 'default     = "s3"' in VARIABLES  # the default scope is the bucket only


def test_each_scope_has_its_own_region_and_the_provider_follows_it() -> None:
    assert 'scope_region = local.full ? "ap-south-1" : "us-east-1"' in MAIN
    assert "region = local.region" in (DEMO / "versions.tf").read_text()
    assert "local.region == local.scope_region" in MAIN  # any other region is refused


def test_full_scope_needs_an_ip_and_the_s3_scope_does_not() -> None:
    assert 'var.my_ip_cidr != ""' in MAIN  # precondition on the security group
    assert re.search(r'variable "my_ip_cidr" \{.*?default\s+= ""', VARIABLES, flags=re.S)


def test_offline_terraform_test_covers_both_scopes() -> None:
    text = (DEMO / "tests" / "scope.tftest.hcl").read_text()
    assert 'mock_provider "aws"' in text  # no AWS call, no credentials
    assert 'demo_scope = "full"' in text and 'demo_scope = "s3"' in text


def test_bucket_has_all_four_public_access_flags_on() -> None:
    block = re.search(r'resource "aws_s3_bucket_public_access_block".*?\n\}\n', MAIN, flags=re.S)
    assert block
    for flag in (
        "block_public_acls",
        "block_public_policy",
        "ignore_public_acls",
        "restrict_public_buckets",
    ):
        assert re.search(rf"{flag}\s*=\s*true", block.group(0)), flag


def test_the_password_output_is_sensitive_and_nothing_secret_is_committed() -> None:
    outputs = (DEMO / "outputs.tf").read_text()
    block = re.search(r'output "db_password" \{.*?\n\}\n', outputs, flags=re.S)
    assert block and "sensitive   = true" in block.group(0)
    for name in (
        "main.tf",
        "variables.tf",
        "outputs.tf",
        "terraform.tfvars.example",
        "README.md",
        "RUNBOOK.md",
    ):
        text = (DEMO / name).read_text()
        assert not re.search(r"AKIA[0-9A-Z]{16}", text), name
        assert not re.search(r"aws_secret_access_key\s*=", text, flags=re.I), name


def test_providers_are_pinned() -> None:
    versions = (DEMO / "versions.tf").read_text()
    assert re.search(r'source\s*=\s*"hashicorp/aws"\s*\n\s*version = "~> \d+\.\d+"', versions)
    assert re.search(r'source\s*=\s*"hashicorp/random"\s*\n\s*version = "~> \d+\.\d+"', versions)
    assert (DEMO / ".terraform.lock.hcl").exists()


def test_local_files_with_secrets_are_ignored_by_git() -> None:
    for path in ("terraform.tfvars", "terraform.tfstate", "terraform.tfstate.backup", ".demo.plan"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", f"demo/aws/{path}"], cwd=ROOT, capture_output=True
        )
        assert result.returncode == 0, path
    # the example file must NOT be ignored, or it could not be committed
    result = subprocess.run(
        ["git", "check-ignore", "-q", "demo/aws/terraform.tfvars.example"], cwd=ROOT
    )
    assert result.returncode == 1


def _statements(name: str) -> list[dict]:
    return json.loads((DEMO / name).read_text())["Statement"]


def test_iam_policies_are_valid_and_have_no_admin_wildcards() -> None:
    for name in POLICIES:
        statements = _statements(name)
        assert statements
        for s in statements:
            assert s["Effect"] == "Allow" and s["Sid"]
            actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
            assert all(a != "*" and not a.endswith(":*") for a in actions), (name, s["Sid"])
        assert (
            len(re.sub(r"\s", "", json.dumps(statements))) < 6000
        )  # managed policy limit is 6,144


def test_read_only_policy_has_no_write_action() -> None:
    for s in _statements("iam-policy-driftpilot-readonly.json"):
        for action in s["Action"]:
            verb = action.split(":")[1]
            assert not verb.startswith(WRITE_VERBS), action


def test_operator_policy_scopes_every_write_to_the_demo() -> None:
    for s in _statements("iam-policy-demo-operator.json"):
        writes = [a for a in s["Action"] if a.split(":")[1].startswith(WRITE_VERBS)]
        if not writes or writes == ["iam:CreateServiceLinkedRole"]:
            continue
        resources = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
        assert "*" not in resources, s["Sid"]
        named = all("driftpilot-demo" in r for r in resources)
        assert named or "Condition" in s, s["Sid"]  # scoped by name, or by tag/region condition
    ec2_change = next(
        s
        for s in _statements("iam-policy-demo-operator.json")
        if s["Sid"] == "Ec2ChangeDemoSecurityGroups"
    )
    assert ec2_change["Condition"]["StringEquals"]["aws:ResourceTag/demo"] == "driftpilot"
