"""AWS demo scenarios 20-24, against moto (an offline mock of AWS). No real AWS is ever called."""

import importlib.util
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

SCRIPT = Path(__file__).parents[1] / "scripts" / "inject_drift.py"
spec = importlib.util.spec_from_file_location("inject_drift_aws", SCRIPT)
inject_drift = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inject_drift)

REGION = "ap-south-1"
DEMO = [{"Key": "demo", "Value": "driftpilot"}, {"Key": "team", "Value": "platform"}]
OTHER = [{"Key": "team", "Value": "someone-else"}]
BUCKET = "driftpilot-demo-abcd1234"


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    """Moto needs some credentials; these are fake and never leave the process."""
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_REGION", REGION)
    monkeypatch.setenv("DRIFTPILOT_AWS_DEMO", "1")
    monkeypatch.delenv("DRIFTPILOT_AWS_DEMO_PUBLIC", raising=False)


@pytest.fixture
def demo():
    """A demo-shaped account: tagged bucket, security group and database."""
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        s3.put_bucket_tagging(Bucket=BUCKET, Tagging={"TagSet": DEMO})
        s3.put_public_access_block(
            Bucket=BUCKET,
            PublicAccessBlockConfiguration=dict.fromkeys(
                (
                    "BlockPublicAcls",
                    "IgnorePublicAcls",
                    "BlockPublicPolicy",
                    "RestrictPublicBuckets",
                ),
                True,
            ),
        )
        ec2 = boto3.client("ec2", region_name=REGION)
        vpc = ec2.describe_vpcs()["Vpcs"][0]["VpcId"]
        group = ec2.create_security_group(
            GroupName="driftpilot-demo-db",
            Description="demo",
            VpcId=vpc,
            TagSpecifications=[{"ResourceType": "security-group", "Tags": DEMO}],
        )["GroupId"]
        ec2.authorize_security_group_ingress(
            GroupId=group,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 5432,
                    "ToPort": 5432,
                    "IpRanges": [{"CidrIp": "203.0.113.7/32"}],
                }
            ],
        )
        rds = boto3.client("rds", region_name=REGION)
        rds.create_db_instance(
            DBInstanceIdentifier="driftpilot-demo-db",
            DBInstanceClass="db.t4g.micro",
            Engine="postgres",
            MasterUsername="appowner",
            MasterUserPassword="not-a-real-password",
            AllocatedStorage=20,
            BackupRetentionPeriod=1,
            PubliclyAccessible=True,
            Tags=DEMO,
        )
        yield {"s3": s3, "ec2": ec2, "rds": rds, "group": group}


def run(action: str, *numbers: int) -> None:
    inject_drift.main([action, *map(str, numbers)])


def db(demo) -> dict:
    return demo["rds"].describe_db_instances(DBInstanceIdentifier="driftpilot-demo-db")[
        "DBInstances"
    ][0]


def test_20_public_access_block_off_and_back(demo) -> None:
    run("inject", 20)
    flags = demo["s3"].get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
    assert set(flags.values()) == {False}
    run("revert", 20)
    flags = demo["s3"].get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
    assert set(flags.values()) == {True}


def ingress_ports(demo) -> set[tuple[int, str]]:
    group = demo["ec2"].describe_security_groups(GroupIds=[demo["group"]])["SecurityGroups"][0]
    return {
        (p["FromPort"], r["CidrIp"]) for p in group["IpPermissions"] for r in p.get("IpRanges", [])
    }


def test_21_ssh_open_to_world_and_back(demo) -> None:
    run("inject", 21)
    assert (22, "0.0.0.0/0") in ingress_ports(demo)
    run("inject", 21)  # twice is fine
    run("revert", 21)
    assert ingress_ports(demo) == {(5432, "203.0.113.7/32")}
    run("revert", 21)  # nothing to revert is fine


def test_22_backup_retention_zero_and_back(demo) -> None:
    run("inject", 22)
    assert db(demo)["BackupRetentionPeriod"] == 0
    run("revert", 22)
    assert db(demo)["BackupRetentionPeriod"] == 1


def test_23_public_flag_flips_away_from_the_code_and_back(demo) -> None:
    run("inject", 23)  # code says public=true, so the drift is false
    assert db(demo)["PubliclyAccessible"] is False
    run("revert", 23)
    assert db(demo)["PubliclyAccessible"] is True


def test_23_other_direction_when_the_code_says_private(demo, monkeypatch) -> None:
    monkeypatch.setenv("DRIFTPILOT_AWS_DEMO_PUBLIC", "false")
    demo["rds"].modify_db_instance(
        DBInstanceIdentifier="driftpilot-demo-db", PubliclyAccessible=False, ApplyImmediately=True
    )
    run("inject", 23)
    assert db(demo)["PubliclyAccessible"] is True
    run("revert", 23)
    assert db(demo)["PubliclyAccessible"] is False


def test_24_tag_edit_keeps_the_demo_tag_and_reverts(demo) -> None:
    run("inject", 24)
    tags = {t["Key"]: t["Value"] for t in demo["s3"].get_bucket_tagging(Bucket=BUCKET)["TagSet"]}
    assert tags == {"demo": "driftpilot", "team": "platform", "reviewed-by": "hand"}
    run("revert", 24)
    tags = {t["Key"]: t["Value"] for t in demo["s3"].get_bucket_tagging(Bucket=BUCKET)["TagSet"]}
    assert tags == {"demo": "driftpilot", "team": "platform"}


# ---------- safety guards ----------


def test_refuses_without_the_confirmation_variable(demo, monkeypatch) -> None:
    monkeypatch.delenv("DRIFTPILOT_AWS_DEMO")
    with pytest.raises(SystemExit, match="DRIFTPILOT_AWS_DEMO=1"):
        run("inject", 20)
    flags = demo["s3"].get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
    assert set(flags.values()) == {True}


def test_refuses_without_a_region(demo, monkeypatch) -> None:
    monkeypatch.delenv("AWS_REGION")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with pytest.raises(SystemExit, match="AWS_REGION"):
        run("inject", 22)


def test_refuses_an_untagged_bucket(demo) -> None:
    demo["s3"].put_bucket_tagging(Bucket=BUCKET, Tagging={"TagSet": OTHER})
    with pytest.raises(SystemExit, match="exactly one bucket"):
        run("inject", 20)
    flags = demo["s3"].get_public_access_block(Bucket=BUCKET)["PublicAccessBlockConfiguration"]
    assert set(flags.values()) == {True}


def test_ignores_a_tagged_bucket_with_the_wrong_name(demo) -> None:
    """A bucket tagged demo=driftpilot but not named driftpilot-demo-* is not the demo bucket."""
    demo["s3"].delete_bucket_tagging(Bucket=BUCKET)
    other = "someone-elses-bucket"
    demo["s3"].create_bucket(Bucket=other, CreateBucketConfiguration={"LocationConstraint": REGION})
    demo["s3"].put_bucket_tagging(Bucket=other, Tagging={"TagSet": DEMO})
    with pytest.raises(SystemExit, match="exactly one bucket"):
        run("inject", 20)


def test_refuses_an_untagged_security_group(demo) -> None:
    demo["ec2"].delete_tags(Resources=[demo["group"]], Tags=[{"Key": "demo"}])
    with pytest.raises(SystemExit, match="security group"):
        run("inject", 21)
    assert ingress_ports(demo) == {(5432, "203.0.113.7/32")}


def test_refuses_an_untagged_database(demo) -> None:
    arn = db(demo)["DBInstanceArn"]
    demo["rds"].remove_tags_from_resource(ResourceName=arn, TagKeys=["demo"])
    with pytest.raises(SystemExit, match="not tagged demo=driftpilot"):
        run("inject", 22)
    assert db(demo)["BackupRetentionPeriod"] == 1


def test_no_demo_resources_means_nothing_happens() -> None:
    with mock_aws():
        for number in (20, 21, 22, 23, 24):
            with pytest.raises(SystemExit):
                run("inject", number)
