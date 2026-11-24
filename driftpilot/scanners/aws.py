"""AWS scanner: S3 buckets, security groups and IAM users that aren't in state.

Read-only calls only (list/describe). The client is injected so tests can use moto, an offline
mock of AWS. Everything shown here is a platform name or ID; nothing is created or changed.
"""

from typing import Any

from driftpilot.models import ScannedResource, UnmanagedFinding
from driftpilot.scanners.base import ImportTarget, state_resources, tf_name

PROVIDER = "registry.terraform.io/hashicorp/aws"
RESOURCE_TYPES = ("s3_bucket", "security_group", "iam_user")
_TF_TYPES = {
    "s3_bucket": "aws_s3_bucket",
    "security_group": "aws_security_group",
    "iam_user": "aws_iam_user",
}


def import_target(u: UnmanagedFinding) -> ImportTarget | None:
    tf_type = _TF_TYPES.get(u.resource_kind)
    if tf_type is None:
        return None
    return ImportTarget(tf_type, u.resource_id, tf_name(u.name))


def _bucket_region(s3: Any, name: str) -> str | None:
    """The bucket's region; None if it can't be read (kept, so a person still sees the bucket)."""
    try:
        location = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
    except Exception:  # e.g. AccessDenied: better to list it than to hide it
        return None
    return {None: "us-east-1", "": "us-east-1", "EU": "eu-west-1"}.get(location, location)


class AWSScanner:
    provider = PROVIDER

    def __init__(
        self,
        session: Any,
        region: str,
        ignore_names: list[str],
        include_names: list[str] | None = None,
        resource_types: list[str] | None = None,
    ) -> None:
        self.session = session  # boto3.Session; injected so tests can use moto
        self.region = region
        self.ignore_names = ignore_names
        self.include_names = include_names or ["*"]
        self.resource_types = resource_types or list(RESOURCE_TYPES)

    def _buckets(self) -> list[ScannedResource]:
        s3 = self.session.client("s3", region_name=self.region)
        found = []
        for b in s3.list_buckets().get("Buckets", []):
            region = _bucket_region(s3, b["Name"])
            if region not in (None, self.region):
                continue  # another region's deployment owns it
            found.append(
                ScannedResource(
                    provider=PROVIDER,
                    resource_kind="s3_bucket",
                    resource_id=b["Name"],
                    name=b["Name"],
                    created_at=b.get("CreationDate"),
                )  # fmt: skip
            )
        return found

    def _security_groups(self) -> list[ScannedResource]:
        ec2 = self.session.client("ec2", region_name=self.region)
        pages = ec2.get_paginator("describe_security_groups").paginate()
        return [
            ScannedResource(
                provider=PROVIDER,
                resource_kind="security_group",
                resource_id=g["GroupId"],
                name=g["GroupName"],
            )  # fmt: skip
            for page in pages
            for g in page.get("SecurityGroups", [])
            if g["GroupName"] != "default"  # every VPC has one; Terraform only adopts it
        ]

    def _users(self) -> list[ScannedResource]:
        iam = self.session.client("iam")
        pages = iam.get_paginator("list_users").paginate()
        return [
            ScannedResource(
                provider=PROVIDER,
                resource_kind="iam_user",
                resource_id=u["UserName"],
                name=u["UserName"],
                created_at=u.get("CreateDate"),
            )  # fmt: skip
            for page in pages
            for u in page.get("Users", [])
        ]

    def list_resources(self) -> list[ScannedResource]:
        listers = {
            "s3_bucket": self._buckets,
            "security_group": self._security_groups,
            "iam_user": self._users,
        }
        return [r for kind in self.resource_types for r in listers[kind]()]

    def managed_ids(self, state: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        for r in state_resources(state):
            if r.get("mode") != "managed":
                continue
            values = r.get("values") or {}
            if r.get("type") == "aws_s3_bucket" and values.get("bucket"):
                ids.add(values["bucket"])
            elif r.get("type") == "aws_security_group" and values.get("id"):
                ids.add(values["id"])
            elif r.get("type") == "aws_iam_user" and values.get("name"):
                ids.add(values["name"])
        return ids
