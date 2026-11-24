"""Inject and revert the drift scenarios from SPEC §7 and the database demo (demo helper).

    python scripts/inject_drift.py list
    python scripts/inject_drift.py inject 2 3 5
    python scripts/inject_drift.py revert 2 3 5 --tf-dir ../driftpilot-infra/infra

GitHub scenarios need GITHUB_TOKEN (the demo org's fine-grained PAT). Revert values match the
Terraform code in demo/github and demo/docker; keep them in sync if that code changes.
Scenarios 1 and 10 delete a resource, so reverting them means `terraform apply` (needs --tf-dir).

Scenarios 15-19 change the local Postgres demo in demo/postgres (docker compose up -d first), as
its owner role `app`. They only ever connect to localhost (set DRIFTPILOT_DEMO_ADMIN_URL for
another port).

Scenarios 20-26 change the real AWS demo in demo/aws (see its README). They need
DRIFTPILOT_AWS_DEMO=1, credentials from AWS_PROFILE, and they refuse to touch any resource that is
not tagged demo=driftpilot. The demo has two scopes (`demo_scope` in demo/aws/terraform.tfvars, or
DRIFTPILOT_AWS_DEMO_SCOPE): "s3" (default, us-east-1) allows 20, 24, 25 and 26 on the bucket;
"full" (ap-south-1) also allows 21-23 (security group, RDS). The region comes from AWS_REGION (or
AWS_DEFAULT_REGION), defaults to the scope's region, and any other region is refused.
"""

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ORG = "driftpilot-demo"
API_REPO, WEB_REPO, HANDMADE_REPO = "demo-api", "demo-web", "demo-handmade"
TEAM = "developers"
API_DESCRIPTION = "DriftPilot demo service (managed by Terraform)"
TOPICS = ["driftpilot", "demo"]
REQUIRED_APPROVALS = 2
HOTFIX_CHECK = "ci/hotfix-check"

WEB_CONTAINER, CACHE_CONTAINER, HANDMADE_CONTAINER = (
    "driftpilot-demo-web",
    "driftpilot-demo-cache",
    "driftpilot-handmade",
)
MANAGED_LABELS = {"managed-by": "terraform", "app": "driftpilot-demo"}
DEMO_DB_URL = "postgresql://app:app@localhost:5433/appdb"  # demo/postgres, local only

AWS_DEMO_TAG = ("demo", "driftpilot")  # the only resources the AWS scenarios may touch
AWS_BUCKET_PREFIX = "driftpilot-demo-"
AWS_SG_NAME = "driftpilot-demo-db"
AWS_DB_ID = "driftpilot-demo-db"
AWS_HAND_TAG = ("reviewed-by", "hand")  # scenario 24 adds this tag
AWS_SCOPE_REGIONS = {"s3": "us-east-1", "full": "ap-south-1"}
AWS_TFVARS = Path(__file__).resolve().parents[1] / "demo" / "aws" / "terraform.tfvars"


@dataclass
class Scenario:
    number: int
    provider: str
    description: str
    expected: str
    inject: Callable[[argparse.Namespace], None]
    revert: Callable[[argparse.Namespace], None]


# ---------- clients ----------


@cache
def github() -> Any:
    from github import Auth, Github

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("GITHUB_TOKEN is not set")
    return Github(auth=Auth.Token(token))


def repo(name: str) -> Any:
    return github().get_repo(f"{ORG}/{name}")


def main_branch() -> Any:
    return repo(API_REPO).get_branch("main")


@cache
def docker_client() -> Any:
    import docker

    return docker.from_env()


def container(name: str) -> Any:
    return docker_client().containers.get(name)


def terraform_apply(args: argparse.Namespace, why: str) -> None:
    """Recreate deleted resources from code, then accept the provider's first-refresh defaults."""
    if not args.tf_dir:
        print(
            f"  {why}: run `terraform apply` (then `terraform apply -refresh-only`) in the demo dir"
        )
        return
    for cmd in (["apply", "-auto-approve"], ["apply", "-refresh-only", "-auto-approve"]):
        subprocess.run(
            ["terraform", *cmd, "-input=false", "-no-color"], cwd=args.tf_dir, check=True
        )


def noop(_: argparse.Namespace) -> None:
    pass


# ---------- GitHub scenarios ----------


def s1_inject(_: argparse.Namespace) -> None:
    main_branch().remove_protection()


def s1_revert(args: argparse.Namespace) -> None:
    # A rule recreated through the API gets a new ID that state doesn't know, so use Terraform.
    terraform_apply(args, "recreate branch protection")


def set_approvals(count: int) -> None:
    main_branch().edit_required_pull_request_reviews(required_approving_review_count=count)


def set_team_permission(permission: str) -> None:
    team = github().get_organization(ORG).get_team_by_slug(TEAM)
    team.update_team_repository(repo(API_REPO), permission)


def s5_inject(_: argparse.Namespace) -> None:
    # Status checks aren't enabled on the rule yet, so the PATCH endpoint would 404;
    # re-PUT the whole rule with the *current* approvals plus one check (an "incident" check),
    # so running it together with scenario 2 doesn't undo that one.
    branch = main_branch()
    approvals = branch.get_required_pull_request_reviews().required_approving_review_count
    branch.edit_protection(
        strict=False, contexts=[HOTFIX_CHECK], required_approving_review_count=approvals
    )


def s5_revert(_: argparse.Namespace) -> None:
    main_branch().remove_required_status_checks()


def s4_revert(_: argparse.Namespace) -> None:
    web = repo(WEB_REPO)
    web.edit(archived=False)
    # Archiving also switches off vulnerability alerts, and unarchiving doesn't switch them back.
    web.enable_vulnerability_alert()


def s9_inject(_: argparse.Namespace) -> None:
    github().get_organization(ORG).create_repo(
        HANDMADE_REPO, description="Created by hand outside Terraform", private=False
    )


def s9_revert(_: argparse.Namespace) -> None:
    repo(HANDMADE_REPO).delete()


# ---------- Docker scenarios ----------


def s10_inject(_: argparse.Namespace) -> None:
    container(CACHE_CONTAINER).remove(force=True)


def s10_revert(args: argparse.Namespace) -> None:
    terraform_apply(args, "recreate the cache container")


def set_memory(mem: str, swap: str) -> None:
    container(WEB_CONTAINER).update(mem_limit=mem, memswap_limit=swap)


def set_restart(policy: dict[str, Any]) -> None:
    container(WEB_CONTAINER).update(restart_policy=policy)


def s13_inject(_: argparse.Namespace) -> None:
    docker_client().containers.run(
        "nginx:alpine", name=HANDMADE_CONTAINER, labels=MANAGED_LABELS, detach=True
    )


def s13_revert(_: argparse.Namespace) -> None:
    container(HANDMADE_CONTAINER).remove(force=True)


# ---------- Postgres scenarios (demo/postgres, local Docker only) ----------


def pg_run(*statements: str) -> None:
    """Run SQL as the demo's owner role. Refuses any database that is not on this machine."""
    url = os.environ.get("DRIFTPILOT_DEMO_ADMIN_URL", DEMO_DB_URL)
    if urlparse(url).hostname not in ("localhost", "127.0.0.1", "::1"):
        sys.exit("refusing to run: the demo database must be on localhost")
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)


def pg(inject: str, revert: str) -> tuple[Callable, Callable]:
    return lambda _: pg_run(inject), lambda _: pg_run(revert)


PG_SCENARIOS = {
    15: ("RLS switched off on orders", "critical / revert",
         "ALTER TABLE orders DISABLE ROW LEVEL SECURITY",
         "ALTER TABLE orders ENABLE ROW LEVEL SECURITY"),
    16: ("NOT NULL dropped on users.email", "high / revert",
         "ALTER TABLE users ALTER COLUMN email DROP NOT NULL",
         "ALTER TABLE users ALTER COLUMN email SET NOT NULL"),
    17: ("Column ssn added to users", "high / investigate",
         "ALTER TABLE users ADD COLUMN ssn text", "ALTER TABLE users DROP COLUMN IF EXISTS ssn"),
    18: ("GRANT SELECT ON orders TO PUBLIC", "critical / revert",
         "GRANT SELECT ON orders TO PUBLIC", "REVOKE SELECT ON orders FROM PUBLIC"),
    19: ("Harmless column nickname added to users", "medium / codify",
         "ALTER TABLE users ADD COLUMN nickname text",
         "ALTER TABLE users DROP COLUMN IF EXISTS nickname"),
}  # fmt: skip

# ---------- AWS scenarios (demo/aws, real AWS: only resources tagged demo=driftpilot) ----------


def aws_scope() -> str:
    """The demo scope: DRIFTPILOT_AWS_DEMO_SCOPE, else demo_scope in terraform.tfvars, else s3."""
    scope = os.environ.get("DRIFTPILOT_AWS_DEMO_SCOPE", "")
    if not scope and AWS_TFVARS.exists():
        for line in AWS_TFVARS.read_text().splitlines():
            match = re.match(r'\s*demo_scope\s*=\s*"([\w-]*)"', line)
            if match:
                scope = match.group(1)
    scope = scope or "s3"
    if scope not in AWS_SCOPE_REGIONS:
        sys.exit(f"refusing to run: unknown demo scope {scope!r} (use s3 or full)")
    return scope


def aws_session(needs_full: bool = False) -> Any:
    """A boto3 session for the demo region. Refuses to run unless DRIFTPILOT_AWS_DEMO=1.

    `needs_full` marks the scenarios that act on the security group or the database.
    """
    if os.environ.get("DRIFTPILOT_AWS_DEMO") != "1":
        sys.exit("refusing to run: set DRIFTPILOT_AWS_DEMO=1 to confirm you mean the AWS demo")
    scope = aws_scope()
    if needs_full and scope != "full":
        sys.exit(
            "refusing to run: this scenario needs the full demo scope (security group or "
            'database); the demo is in the "s3" scope'
        )
    expected = AWS_SCOPE_REGIONS[scope]
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or expected
    if region != expected:
        sys.exit(f"refusing to run: the {scope} scope runs in {expected}, not {region}")
    import boto3

    return boto3.Session(region_name=region)


def is_demo_tagged(tags: dict[str, str]) -> bool:
    return tags.get(AWS_DEMO_TAG[0]) == AWS_DEMO_TAG[1]


def tags_of(pairs: list[dict[str, str]]) -> dict[str, str]:
    """Turns [{"Key": k, "Value": v}] (or lower-case keys, for tag filters) into a dict."""
    return {(p.get("Key") or p.get("key")): (p.get("Value") or p.get("value")) for p in pairs}


def bucket_tags(s3: Any, name: str) -> dict[str, str]:
    from botocore.exceptions import ClientError

    try:
        return tags_of(s3.get_bucket_tagging(Bucket=name)["TagSet"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchTagSet":
            return {}
        raise


def demo_bucket(session: Any) -> tuple[Any, str]:
    """The demo bucket: named driftpilot-demo-* AND tagged demo=driftpilot. Exactly one."""
    s3 = session.client("s3")
    names = [
        b["Name"]
        for b in s3.list_buckets().get("Buckets", [])
        if b["Name"].startswith(AWS_BUCKET_PREFIX) and is_demo_tagged(bucket_tags(s3, b["Name"]))
    ]
    if len(names) != 1:
        sys.exit(f"expected exactly one bucket tagged demo=driftpilot, found {len(names)}")
    return s3, names[0]


def demo_security_group(session: Any) -> tuple[Any, str]:
    ec2 = session.client("ec2")
    groups = ec2.describe_security_groups(
        Filters=[
            {"Name": f"tag:{AWS_DEMO_TAG[0]}", "Values": [AWS_DEMO_TAG[1]]},
            {"Name": "group-name", "Values": [AWS_SG_NAME]},
        ]
    )["SecurityGroups"]
    groups = [g for g in groups if is_demo_tagged(tags_of(g.get("Tags", [])))]
    if len(groups) != 1:
        sys.exit(f"expected exactly one security group tagged demo=driftpilot, found {len(groups)}")
    return ec2, groups[0]["GroupId"]


def demo_db(session: Any) -> tuple[Any, str]:
    rds = session.client("rds")
    from botocore.exceptions import ClientError

    try:
        db = rds.describe_db_instances(DBInstanceIdentifier=AWS_DB_ID)["DBInstances"][0]
    except ClientError as e:
        sys.exit(f"demo database {AWS_DB_ID} not found: {e.response['Error']['Code']}")
    tags = tags_of(rds.list_tags_for_resource(ResourceName=db["DBInstanceArn"])["TagList"])
    if not is_demo_tagged(tags):
        sys.exit(f"refusing to touch {AWS_DB_ID}: it is not tagged demo=driftpilot")
    return rds, db["DBInstanceIdentifier"]


def set_public_access_block(blocked: bool) -> None:
    s3, bucket = demo_bucket(aws_session())
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": blocked,
            "IgnorePublicAcls": blocked,
            "BlockPublicPolicy": blocked,
            "RestrictPublicBuckets": blocked,
        },
    )


def ssh_open_to_world() -> list[dict[str, Any]]:
    return [
        {
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "hotfix: temporary ssh"}],
        }
    ]


def change_ssh_rule(open_it: bool) -> None:
    from botocore.exceptions import ClientError

    ec2, group_id = demo_security_group(aws_session(needs_full=True))
    call = ec2.authorize_security_group_ingress if open_it else ec2.revoke_security_group_ingress
    try:
        call(GroupId=group_id, IpPermissions=ssh_open_to_world())
    except ClientError as e:  # already open / already closed: nothing to do
        if e.response["Error"]["Code"] not in (
            "InvalidPermission.Duplicate",
            "InvalidPermission.NotFound",
        ):
            raise


def set_backup_retention(days: int) -> None:
    rds, identifier = demo_db(aws_session(needs_full=True))
    rds.modify_db_instance(
        DBInstanceIdentifier=identifier, BackupRetentionPeriod=days, ApplyImmediately=True
    )


def public_baseline() -> bool:
    """The `publicly_accessible` value in demo/aws (var.db_publicly_accessible, default true)."""
    return os.environ.get("DRIFTPILOT_AWS_DEMO_PUBLIC", "true").lower() != "false"


def set_publicly_accessible(value: bool) -> None:
    rds, identifier = demo_db(aws_session(needs_full=True))
    rds.modify_db_instance(
        DBInstanceIdentifier=identifier, PubliclyAccessible=value, ApplyImmediately=True
    )


def edit_bucket_tag(add: bool) -> None:
    s3, bucket = demo_bucket(aws_session())
    tags = bucket_tags(s3, bucket)
    if add:
        tags[AWS_HAND_TAG[0]] = AWS_HAND_TAG[1]
    else:
        tags.pop(AWS_HAND_TAG[0], None)
    # demo=driftpilot is always kept, so the guard still recognises the bucket afterwards
    s3.put_bucket_tagging(
        Bucket=bucket, Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]}
    )


def set_versioning(enabled: bool) -> None:
    s3, bucket = demo_bucket(aws_session())
    s3.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled" if enabled else "Suspended"}
    )


def remove_default_encryption(removed: bool) -> None:
    """Scenario 26. Revert puts back the SSE-S3 default the code sets (sse_algorithm = AES256)."""
    s3, bucket = demo_bucket(aws_session())
    if removed:
        s3.delete_bucket_encryption(Bucket=bucket)
    else:
        s3.put_bucket_encryption(
            Bucket=bucket,
            ServerSideEncryptionConfiguration={
                "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
            },
        )


SCENARIOS = {
    s.number: s
    for s in [
        Scenario(1, "github", "Branch protection on demo-api main deleted", "critical / revert",
                 s1_inject, s1_revert),
        Scenario(2, "github", "Required approvals 2 -> 0", "critical / revert",
                 lambda _: set_approvals(0), lambda _: set_approvals(REQUIRED_APPROVALS)),
        Scenario(3, "github", "Team developers access pull -> admin", "high / revert",
                 lambda _: set_team_permission("admin"), lambda _: set_team_permission("pull")),
        Scenario(4, "github", "demo-web archived", "high / investigate",
                 lambda _: repo(WEB_REPO).edit(archived=True), s4_revert),
        Scenario(5, "github", f"Required status check '{HOTFIX_CHECK}' added", "medium / codify",
                 s5_inject, s5_revert),
        Scenario(6, "github", "has_issues turned off on demo-api", "medium / codify or revert",
                 lambda _: repo(API_REPO).edit(has_issues=False),
                 lambda _: repo(API_REPO).edit(has_issues=True)),
        Scenario(7, "github", "demo-api description edited", "low / codify",
                 lambda _: repo(API_REPO).edit(description="Hotfix: edited by hand"),
                 lambda _: repo(API_REPO).edit(description=API_DESCRIPTION)),
        Scenario(8, "github", "demo-api topics changed", "low / codify",
                 lambda _: repo(API_REPO).replace_topics([*TOPICS, "hotfix"]),
                 lambda _: repo(API_REPO).replace_topics(TOPICS)),
        Scenario(9, "github", f"New repo {HANDMADE_REPO} created by hand", "unmanaged / import",
                 s9_inject, s9_revert),
        Scenario(10, "docker", "Cache container removed (docker rm -f)", "high / recreate",
                 s10_inject, s10_revert),
        Scenario(11, "docker", "Web memory 256m -> 512m", "medium / codify or revert",
                 lambda _: set_memory("512m", "1g"), lambda _: set_memory("256m", "512m")),
        Scenario(12, "docker", "Web restart policy -> on-failure:3", "medium / codify",
                 lambda _: set_restart({"Name": "on-failure", "MaximumRetryCount": 3}),
                 lambda _: set_restart({"Name": "unless-stopped", "MaximumRetryCount": 0})),
        Scenario(13, "docker", "Labelled container started by hand", "unmanaged / import",
                 s13_inject, s13_revert),
        Scenario(14, "both", "No change (control)", "nothing reported", noop, noop),
        *(
            Scenario(n, "postgres", desc, expected, *pg(inject, revert))
            for n, (desc, expected, inject, revert) in PG_SCENARIOS.items()
        ),
        Scenario(20, "aws", "S3 public access block switched off on the demo bucket",
                 "critical / revert",
                 lambda _: set_public_access_block(False), lambda _: set_public_access_block(True)),
        Scenario(21, "aws", "[full scope] Security group opens SSH (22) to 0.0.0.0/0",
                 "critical / revert",
                 lambda _: change_ssh_rule(True), lambda _: change_ssh_rule(False)),
        Scenario(22, "aws", "[full scope] RDS backup retention 1 -> 0 days", "high / revert",
                 lambda _: set_backup_retention(0), lambda _: set_backup_retention(1)),
        Scenario(23, "aws", "[full scope] RDS publicly_accessible flipped from the code's value",
                 "critical if turned on, otherwise ask a person",
                 lambda _: set_publicly_accessible(not public_baseline()),
                 lambda _: set_publicly_accessible(public_baseline())),
        Scenario(24, "aws", f"Harmless tag {AWS_HAND_TAG[0]}={AWS_HAND_TAG[1]} added to the bucket",
                 "low / codify",
                 lambda _: edit_bucket_tag(True), lambda _: edit_bucket_tag(False)),
        Scenario(25, "aws", "S3 bucket versioning suspended", "high / revert",
                 lambda _: set_versioning(False), lambda _: set_versioning(True)),
        Scenario(26, "aws", "S3 bucket default encryption removed", "critical / revert",
                 lambda _: remove_default_encryption(True),
                 lambda _: remove_default_encryption(False)),
    ]
}  # fmt: skip


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["list", "inject", "revert"])
    parser.add_argument("scenarios", nargs="*", type=int, help="scenario numbers (1-26)")
    parser.add_argument("--tf-dir", type=Path, help="Terraform dir for reverts that need apply")
    args = parser.parse_args(argv)

    if args.command == "list":
        for s in SCENARIOS.values():
            print(f"{s.number:>2}  {s.provider:<6}  {s.description:<48}  expected: {s.expected}")
        return
    unknown = [n for n in args.scenarios if n not in SCENARIOS]
    if not args.scenarios or unknown:
        parser.error(f"give scenario numbers 1-26 (unknown: {unknown})")
    for number in args.scenarios:
        scenario = SCENARIOS[number]
        print(f"{args.command} {number}: {scenario.description}")
        getattr(scenario, args.command)(args)


if __name__ == "__main__":
    main()
