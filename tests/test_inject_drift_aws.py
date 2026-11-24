"""AWS demo scenarios 20-26, against moto (an offline mock of AWS). No real AWS is ever called."""

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


S3_REGION = "us-east-1"


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch, tmp_path):
    """Moto needs some credentials; these are fake and never leave the process."""
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setenv("AWS_REGION", REGION)
    monkeypatch.setenv(
        "DRIFTPILOT_AWS_DEMO_SCOPE", "full"
    )  # the tests below start in the full scope
    monkeypatch.setattr(inject_drift, "AWS_TFVARS", tmp_path / "terraform.tfvars")
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


def test_region_defaults_to_the_scopes_region_and_other_regions_are_refused(
    demo, monkeypatch
) -> None:
    monkeypatch.delenv("AWS_REGION")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    run("inject", 22)  # full scope: ap-south-1 by default
    assert db(demo)["BackupRetentionPeriod"] == 0
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    with pytest.raises(SystemExit, match="full scope runs in ap-south-1"):
        run("inject", 22)
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    with pytest.raises(SystemExit, match="not eu-west-1"):
        run("inject", 20)


def test_25_versioning_suspended_and_back(demo) -> None:
    run("inject", 25)
    assert demo["s3"].get_bucket_versioning(Bucket=BUCKET)["Status"] == "Suspended"
    run("revert", 25)
    assert demo["s3"].get_bucket_versioning(Bucket=BUCKET)["Status"] == "Enabled"


def encryption(demo) -> list[dict]:
    config = demo["s3"].get_bucket_encryption(Bucket=BUCKET)["ServerSideEncryptionConfiguration"]
    return [r["ApplyServerSideEncryptionByDefault"]["SSEAlgorithm"] for r in config["Rules"]]


def test_26_default_encryption_removed_and_back(demo) -> None:
    from botocore.exceptions import ClientError

    run("inject", 26)
    with pytest.raises(ClientError, match="ServerSideEncryptionConfigurationNotFoundError"):
        demo["s3"].get_bucket_encryption(Bucket=BUCKET)
    run("revert", 26)
    assert encryption(demo) == ["AES256"]


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
        for number in (20, 21, 22, 23, 24, 25, 26):
            with pytest.raises(SystemExit):
                run("inject", number)


# ---------- the "s3" scope: one bucket in us-east-1, no EC2, no RDS ----------


@pytest.fixture
def s3_demo(monkeypatch):
    monkeypatch.setenv("DRIFTPILOT_AWS_DEMO_SCOPE", "s3")
    monkeypatch.setenv("AWS_REGION", S3_REGION)
    with mock_aws():
        s3 = boto3.client("s3", region_name=S3_REGION)
        s3.create_bucket(Bucket=BUCKET)  # us-east-1 takes no LocationConstraint
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
        s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
        s3.put_bucket_encryption(
            Bucket=BUCKET,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )
        yield {"s3": s3}


def flags(s3_demo) -> set[bool]:
    config = s3_demo["s3"].get_public_access_block(Bucket=BUCKET)
    return set(config["PublicAccessBlockConfiguration"].values())


def test_s3_scope_defaults_to_us_east_1_without_any_region_variable(s3_demo, monkeypatch) -> None:
    monkeypatch.delenv("AWS_REGION")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    run("inject", 20)
    assert flags(s3_demo) == {False}
    run("revert", 20)
    assert flags(s3_demo) == {True}


def test_s3_scope_is_the_default_when_nothing_is_set(s3_demo, monkeypatch) -> None:
    monkeypatch.delenv("DRIFTPILOT_AWS_DEMO_SCOPE")
    run("inject", 20)
    assert flags(s3_demo) == {False}


def test_scope_can_be_read_from_terraform_tfvars(s3_demo, monkeypatch) -> None:
    monkeypatch.delenv("DRIFTPILOT_AWS_DEMO_SCOPE")
    inject_drift.AWS_TFVARS.write_text('my_ip_cidr = "198.51.100.9/32"\ndemo_scope = "full"\n')
    with pytest.raises(SystemExit, match="full scope runs in ap-south-1"):
        run("inject", 20)  # the file says full, but the region is us-east-1
    assert flags(s3_demo) == {True}


def test_s3_scope_runs_the_four_bucket_scenarios_and_reverts_them(s3_demo) -> None:
    run("inject", 20, 24, 25, 26)
    assert flags(s3_demo) == {False}
    tags = {t["Key"]: t["Value"] for t in s3_demo["s3"].get_bucket_tagging(Bucket=BUCKET)["TagSet"]}
    assert tags["reviewed-by"] == "hand" and tags["demo"] == "driftpilot"
    assert s3_demo["s3"].get_bucket_versioning(Bucket=BUCKET)["Status"] == "Suspended"
    with pytest.raises(Exception, match="ServerSideEncryptionConfigurationNotFoundError"):
        s3_demo["s3"].get_bucket_encryption(Bucket=BUCKET)
    run("revert", 26, 25, 24, 20)
    assert flags(s3_demo) == {True}
    tags = {t["Key"]: t["Value"] for t in s3_demo["s3"].get_bucket_tagging(Bucket=BUCKET)["TagSet"]}
    assert tags == {"demo": "driftpilot", "team": "platform"}
    assert s3_demo["s3"].get_bucket_versioning(Bucket=BUCKET)["Status"] == "Enabled"
    assert encryption(s3_demo) == ["AES256"]


@pytest.mark.parametrize("number", [21, 22, 23])
@pytest.mark.parametrize("action", ["inject", "revert"])
def test_s3_scope_refuses_the_security_group_and_database_scenarios(
    s3_demo, number, action
) -> None:
    with pytest.raises(SystemExit, match='needs the full demo scope.*"s3" scope'):
        run(action, number)


def test_s3_scope_refuses_another_region_and_never_touches_ec2_or_rds(s3_demo, monkeypatch) -> None:
    monkeypatch.setenv("AWS_REGION", "ap-south-1")
    with pytest.raises(SystemExit, match="s3 scope runs in us-east-1, not ap-south-1"):
        run("inject", 25)
    assert s3_demo["s3"].get_bucket_versioning(Bucket=BUCKET)["Status"] == "Enabled"


def test_unknown_scope_is_refused(s3_demo, monkeypatch) -> None:
    monkeypatch.setenv("DRIFTPILOT_AWS_DEMO_SCOPE", "everything")
    with pytest.raises(SystemExit, match="unknown demo scope"):
        run("inject", 20)


@pytest.mark.parametrize("number", [20, 24, 25, 26])
def test_s3_scope_guards_still_apply(s3_demo, monkeypatch, number) -> None:
    s3_demo["s3"].put_bucket_tagging(Bucket=BUCKET, Tagging={"TagSet": OTHER})
    with pytest.raises(SystemExit, match="exactly one bucket"):
        run("inject", number)
    monkeypatch.delenv("DRIFTPILOT_AWS_DEMO")
    with pytest.raises(SystemExit, match="DRIFTPILOT_AWS_DEMO=1"):
        run("inject", number)
    assert flags(s3_demo) == {True}
    assert s3_demo["s3"].get_bucket_versioning(Bucket=BUCKET)["Status"] == "Enabled"
    assert encryption(s3_demo) == ["AES256"]
