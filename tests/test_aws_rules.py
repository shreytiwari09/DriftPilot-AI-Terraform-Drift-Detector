"""AWS rules in the default pack: severities, compliance tags and noise."""

import json
from datetime import UTC, datetime

import pytest

from driftpilot.collector import parse_plan, resource_values
from driftpilot.triage.rules import (
    CONTROL_TAGS,
    apply_rules,
    load_never_soften,
    load_rules,
)

NOW = datetime(2026, 10, 25, tzinfo=UTC)
RULES = load_rules()


def one_change(type_: str, before, after, address: str, actions=("update",)) -> dict:
    change = {"actions": list(actions), "before": before, "after": after}
    return {
        "resource_drift": [
            {"address": address, "type": type_, "provider_name": "p", "change": change}
        ]
    }


def decide(type_: str, before, after, actions=("update",)):
    plan = one_change(type_, before, after, address=f"{type_}.x", actions=actions)
    findings = parse_plan(plan, "r", NOW)
    verdicts = apply_rules(findings, RULES, resource_values(plan))
    return {f.attribute_path: verdicts.get(f.id) for f in findings}


def policy(*statements: dict) -> str:
    return json.dumps({"Version": "2012-10-17", "Statement": list(statements)})


ALLOW_S3 = {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::b/*"}


@pytest.mark.parametrize(
    "flag",
    ["block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"],
)
def test_s3_public_access_block_flag_off_is_critical(flag: str) -> None:
    v = decide("aws_s3_bucket_public_access_block", {flag: True}, {flag: False})[flag]
    assert (v.severity, v.recommended_action, v.source) == ("critical", "revert", "rule")
    assert v.controls == ["public-storage"]


def test_s3_public_access_block_turned_on_is_not_a_rule() -> None:
    assert (
        decide(
            "aws_s3_bucket_public_access_block",
            {"block_public_acls": False},
            {"block_public_acls": True},
        )["block_public_acls"]
        is None
    )


def test_account_level_public_access_block_off_is_critical() -> None:
    v = decide(
        "aws_s3_account_public_access_block",
        {"block_public_policy": True},
        {"block_public_policy": False},
    )["block_public_policy"]
    assert v.severity == "critical"


def test_bucket_policy_with_star_principal_is_critical() -> None:
    before = policy({**ALLOW_S3, "Principal": {"AWS": "arn:aws:iam::123456789012:root"}})
    after = policy({**ALLOW_S3, "Principal": "*"})
    v = decide("aws_s3_bucket_policy", {"policy": before}, {"policy": after})["policy"]
    assert (v.severity, v.controls) == ("critical", ["public-storage", "least-privilege"])


def test_bucket_policy_already_public_is_not_decided() -> None:
    before = policy({**ALLOW_S3, "Principal": "*"})
    after = policy({**ALLOW_S3, "Principal": "*", "Action": "s3:ListBucket"})
    assert decide("aws_s3_bucket_policy", {"policy": before}, {"policy": after})["policy"] is None


@pytest.mark.parametrize("type_", ["aws_iam_policy", "aws_iam_role_policy", "aws_iam_user_policy"])
def test_iam_wildcard_action_is_critical(type_: str) -> None:
    before = policy(ALLOW_S3)
    after = policy({"Effect": "Allow", "Action": "*", "Resource": "arn:aws:s3:::b/*"})
    v = decide(type_, {"policy": before}, {"policy": after})["policy"]
    assert (v.severity, v.controls) == ("critical", ["least-privilege"])


def test_iam_wildcard_resource_is_critical() -> None:
    after = policy({"Effect": "Allow", "Action": "s3:GetObject", "Resource": "*"})
    v = decide("aws_iam_policy", {"policy": policy(ALLOW_S3)}, {"policy": after})["policy"]
    assert v.severity == "critical"


@pytest.mark.parametrize("type_", ["aws_db_instance", "aws_rds_cluster_instance"])
def test_rds_made_public_is_critical(type_: str) -> None:
    v = decide(type_, {"publicly_accessible": False}, {"publicly_accessible": True})[
        "publicly_accessible"
    ]
    assert (v.severity, v.controls) == ("critical", ["network-exposure"])


@pytest.mark.parametrize(
    ("type_", "attr", "control"),
    [
        ("aws_db_instance", "storage_encrypted", "encryption-at-rest"),
        ("aws_rds_cluster", "storage_encrypted", "encryption-at-rest"),
        ("aws_ebs_volume", "encrypted", "encryption-at-rest"),
        ("aws_cloudtrail", "enable_logging", "audit-logging"),
    ],
)
def test_encryption_or_logging_turned_off_is_critical(type_: str, attr: str, control: str) -> None:
    v = decide(type_, {attr: True}, {attr: False})[attr]
    assert (v.severity, v.recommended_action, v.controls) == ("critical", "revert", [control])


def test_s3_encryption_configuration_removed_is_critical() -> None:
    v = decide(
        "aws_s3_bucket_server_side_encryption_configuration",
        {"bucket": "b"},
        None,
        actions=("delete",),
    )[None]
    assert (v.severity, v.controls) == ("critical", ["encryption-at-rest"])


def test_backup_retention_decreased_is_high() -> None:
    v = decide("aws_db_instance", {"backup_retention_period": 7}, {"backup_retention_period": 1})[
        "backup_retention_period"
    ]
    assert (v.severity, v.controls) == ("high", ["backup"])
    assert (
        decide("aws_db_instance", {"backup_retention_period": 7}, {"backup_retention_period": 14})[
            "backup_retention_period"
        ]
        is None
    )


def test_deletion_protection_off_is_high() -> None:
    v = decide("aws_db_instance", {"deletion_protection": True}, {"deletion_protection": False})[
        "deletion_protection"
    ]
    assert (v.severity, v.controls) == ("high", ["backup"])


def test_ec2_public_ip_is_high() -> None:
    v = decide(
        "aws_instance",
        {"associate_public_ip_address": False},
        {"associate_public_ip_address": True},
    )["associate_public_ip_address"]
    assert (v.severity, v.controls) == ("high", ["network-exposure"])


def test_open_admin_port_has_network_exposure_tag() -> None:
    ingress = lambda cidr: [  # noqa: E731
        {"cidr_blocks": [cidr], "from_port": 22, "to_port": 22, "protocol": "tcp"}
    ]
    v = decide(
        "aws_security_group", {"ingress": ingress("10.0.0.0/8")}, {"ingress": ingress("0.0.0.0/0")}
    )["ingress[0].cidr_blocks"]
    assert v.controls == ["network-exposure"]


# ---- Noise ----


def test_tags_all_that_mirrors_tags_is_noise() -> None:
    before = {"tags": {"team": "a"}, "tags_all": {"team": "a"}}
    after = {"tags": {"team": "a", "cost": "1"}, "tags_all": {"team": "a", "cost": "1"}}
    out = decide("aws_s3_bucket", before, after)
    assert out["tags.cost"] is None  # the real change stays for triage
    assert out["tags_all.cost"].is_real_drift is False
    assert out["tags_all.cost"].rule_id == "noise-aws-tags-all-mirror"


def test_tags_all_from_provider_default_tags_is_not_noise() -> None:
    """A key that is only in tags_all comes from default_tags (or was set by hand): keep it."""
    before = {"tags": {"team": "a"}, "tags_all": {"team": "a", "env": "prod"}}
    after = {"tags": {"team": "a"}, "tags_all": {"team": "a", "env": "dev"}}
    assert decide("aws_s3_bucket", before, after)["tags_all.env"] is None


def test_tags_all_with_a_different_value_than_tags_is_not_noise() -> None:
    before = {"tags": {"team": "a"}, "tags_all": {"team": "a"}}
    after = {"tags": {"team": "a"}, "tags_all": {"team": "b"}}
    assert decide("aws_s3_bucket", before, after)["tags_all.team"] is None


def test_rds_latest_restorable_time_is_noise() -> None:
    v = decide(
        "aws_db_instance",
        {"latest_restorable_time": "2026-10-25T10:00:00Z"},
        {"latest_restorable_time": "2026-10-25T10:05:00Z"},
    )["latest_restorable_time"]
    assert v.is_real_drift is False and v.rule_id == "noise-aws-rds-latest-restorable-time"


# ---- Pack hygiene ----


def test_every_control_tag_is_known() -> None:
    for rule in RULES:
        assert set(rule.controls) <= CONTROL_TAGS, rule.id
    for entry in load_never_soften():
        assert set(entry.controls) <= CONTROL_TAGS, entry.reason


def test_unknown_control_tag_fails_fast(tmp_path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
rules:
  - id: typo
    controls: [cis-1.1]
    verdict: {is_real_drift: true, severity: high, category: security, intent: unknown,
              recommended_action: revert, confidence: 1, reason: x}
"""
    )
    with pytest.raises(ValueError, match="unknown control tag"):
        load_rules(path)


def test_security_never_soften_entries_have_tags() -> None:
    aws = [e for e in load_never_soften() if e.type.startswith("aws_")]
    assert aws and all(e.controls for e in aws)
