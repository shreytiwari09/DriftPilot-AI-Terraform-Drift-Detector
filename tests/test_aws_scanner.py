"""AWS scanner against moto, an offline mock of AWS. No real account, no network."""

from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from driftpilot.config import Config
from driftpilot.models import UnmanagedFinding
from driftpilot.scanners import build_scanners, import_target
from driftpilot.scanners.aws import PROVIDER, AWSScanner
from driftpilot.scanners.base import find_unmanaged

NOW = datetime(2026, 11, 20, tzinfo=UTC)
REGION = "eu-west-1"


@pytest.fixture(autouse=True)
def fake_aws_credentials(monkeypatch) -> None:
    """moto never sees these; they only keep boto3 from looking for real credentials."""
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


def session() -> boto3.Session:
    return boto3.Session(region_name=REGION)


def scanner(**kwargs) -> AWSScanner:
    return AWSScanner(session(), REGION, kwargs.pop("ignore_names", []), **kwargs)


def make_world() -> dict[str, str]:
    """A bucket in the scanner's region, one elsewhere, two security groups, two IAM users."""
    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(Bucket="acme-data", CreateBucketConfiguration={"LocationConstraint": REGION})
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="us-bucket")
    ec2 = boto3.client("ec2", region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    sg = ec2.create_security_group(GroupName="web", Description="web", VpcId=vpc)["GroupId"]
    iam = boto3.client("iam", region_name=REGION)
    iam.create_user(UserName="alice")
    iam.create_user(UserName="ci-bot")
    return {"vpc": vpc, "sg": sg}


@mock_aws
def test_lists_buckets_in_its_region_security_groups_without_default_and_users() -> None:
    ids = make_world()
    found = {(r.resource_kind, r.name): r for r in scanner().list_resources()}
    assert ("s3_bucket", "acme-data") in found
    assert ("s3_bucket", "us-bucket") not in found  # another region: another deployment's job
    assert ("security_group", "web") in found and found[("security_group", "web")].resource_id == (
        ids["sg"]
    )
    assert not any(k == "security_group" and n == "default" for k, n in found)
    assert {n for k, n in found if k == "iam_user"} == {"alice", "ci-bot"}
    assert all(r.provider == PROVIDER for r in found.values())
    assert found[("iam_user", "alice")].created_at is not None


@mock_aws
def test_resource_types_limit_what_is_listed() -> None:
    make_world()
    kinds = {r.resource_kind for r in scanner(resource_types=["iam_user"]).list_resources()}
    assert kinds == {"iam_user"}


def state(*resources: dict) -> dict:
    return {"values": {"root_module": {"resources": list(resources)}}}


@mock_aws
def test_state_decides_which_resources_are_managed() -> None:
    ids = make_world()
    st = state(
        {
            "type": "aws_s3_bucket",
            "mode": "managed",
            "values": {"bucket": "acme-data", "id": "acme-data"},
        },
        {"type": "aws_security_group", "mode": "managed", "values": {"id": ids["sg"]}},
        {"type": "aws_iam_user", "mode": "managed", "values": {"name": "alice"}},
        {"type": "aws_iam_user", "mode": "data", "values": {"name": "ci-bot"}},  # data source
    )
    unmanaged = find_unmanaged(scanner(), st, "r1", NOW)
    assert [(u.resource_kind, u.name) for u in unmanaged] == [("iam_user", "ci-bot")]


@mock_aws
def test_include_and_ignore_names() -> None:
    make_world()
    st = state()
    found = find_unmanaged(scanner(ignore_names=["ci-*"], include_names=["a*"]), st, "r", NOW)
    assert {(u.resource_kind, u.name) for u in found} == {
        ("s3_bucket", "acme-data"),
        ("iam_user", "alice"),
    }


@mock_aws
def test_module_resources_count_as_managed() -> None:
    make_world()
    st = {
        "values": {
            "root_module": {
                "child_modules": [
                    {
                        "resources": [
                            {"type": "aws_iam_user", "mode": "managed", "values": {"name": "alice"}}
                        ]
                    }
                ]
            }
        }
    }
    names = {u.name for u in find_unmanaged(scanner(resource_types=["iam_user"]), st, "r", NOW)}
    assert names == {"ci-bot"}


@mock_aws
def test_bucket_in_us_east_1_is_found_when_that_is_the_region() -> None:
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="us-bucket")
    found = AWSScanner(boto3.Session(region_name="us-east-1"), "us-east-1", []).list_resources()
    assert [r.name for r in found if r.resource_kind == "s3_bucket"] == ["us-bucket"]


def unmanaged(kind: str, rid: str, name: str) -> UnmanagedFinding:
    return UnmanagedFinding(id="u", run_id="r", detected_at=NOW, provider=PROVIDER,
                            resource_kind=kind, resource_id=rid, name=name)  # fmt: skip


def test_import_targets() -> None:
    t = import_target(unmanaged("s3_bucket", "acme-data", "acme-data"))
    assert (t.tf_type, t.import_id, t.name) == ("aws_s3_bucket", "acme-data", "acme_data")
    t = import_target(unmanaged("security_group", "sg-0abc", "web-tier"))
    assert (t.tf_type, t.import_id, t.address) == ("aws_security_group", "sg-0abc",
                                                  "aws_security_group.web_tier")  # fmt: skip
    t = import_target(unmanaged("iam_user", "ci-bot", "ci-bot"))
    assert (t.tf_type, t.import_id) == ("aws_iam_user", "ci-bot")
    assert import_target(unmanaged("lambda", "x", "x")) is None


def test_config_builds_the_aws_scanner_without_touching_aws(monkeypatch) -> None:
    config = Config.model_validate(
        {"scanners": {"aws": {"region": REGION, "ignore_names": ["tmp-*"],
                              "resource_types": ["s3_bucket"]}}}
    )  # fmt: skip
    [built] = build_scanners(config)
    assert isinstance(built, AWSScanner)
    assert (built.region, built.ignore_names, built.resource_types) == (
        REGION, ["tmp-*"], ["s3_bucket"],
    )  # fmt: skip


def test_unknown_resource_type_in_config_is_rejected() -> None:
    with pytest.raises(ValueError, match="resource_types"):
        Config.model_validate({"scanners": {"aws": {"resource_types": ["ec2"]}}})
