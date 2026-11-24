import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from driftpilot.cloud_events import attach_event_context, load_events, parse_event
from driftpilot.collector import parse_plan, resource_values
from driftpilot.models import DriftFinding, UnmanagedFinding

FIXTURES = Path(__file__).parent / "fixtures" / "aws"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def events(name: str):
    return load_events(FIXTURES / name)


def plan_for(type_: str, address: str, before: dict, after: dict, actions=("update",)) -> dict:
    change = {"actions": list(actions), "before": before, "after": after}
    return {
        "resource_drift": [
            {"address": address, "type": type_, "provider_name": "aws", "change": change}
        ]
    }


def findings_for(plan: dict) -> tuple[list[DriftFinding], dict]:
    return parse_plan(plan, "r1", NOW), resource_values(plan)


# ---- parsing the formats AWS delivers ----


def test_eventbridge_envelope_gives_actor_event_and_request() -> None:
    [event] = events("cloudtrail_put_bucket_policy.json")
    c = event.context
    assert c.event_name == "PutBucketPolicy"
    assert c.event_source == "s3.amazonaws.com"
    assert c.event_time == "2026-11-20T09:41:07Z"
    assert c.actor == "assumed-role/PlatformAdmin/alice"
    assert c.actor_type == "AssumedRole"
    assert c.request["bucketName"] == "acme-data"
    assert "acme-data" in event.identifiers


def test_account_ids_never_reach_the_context() -> None:
    [event] = events("cloudtrail_put_bucket_policy.json")
    assert "123456789012" not in event.context.model_dump_json()


def test_raw_cloudtrail_record_and_root_actor() -> None:
    [event] = events("cloudtrail_stop_logging_raw.json")
    assert (event.context.actor, event.context.actor_type) == ("root", "Root")
    assert event.context.event_name == "StopLogging"
    assert {"main", "trail/main"} & event.identifiers  # name given as a trail ARN


def test_log_file_skips_read_only_and_failed_calls() -> None:
    [event] = events("cloudtrail_log_file.json")
    assert event.context.event_name == "ModifyDBInstance"
    assert event.context.actor == "user/carol"
    assert "main" in event.identifiers
    assert event.context.request["masterUserPassword"] == "[redacted]"


def test_not_an_event_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "e.json"
    path.write_text(json.dumps({"hello": "world"}))
    with pytest.raises(ValueError, match="CloudTrail"):
        load_events(path)
    path.write_text("not json")
    with pytest.raises(ValueError, match="valid JSON"):
        load_events(path)


def test_a_list_of_events_is_accepted(tmp_path: Path) -> None:
    one = json.loads((FIXTURES / "cloudtrail_put_bucket_policy.json").read_text())
    two = json.loads((FIXTURES / "cloudtrail_authorize_sg_ingress.json").read_text())
    path = tmp_path / "e.json"
    path.write_text(json.dumps([one, two]))
    assert [e.context.event_name for e in load_events(path)] == [
        "PutBucketPolicy",
        "AuthorizeSecurityGroupIngress",
    ]


# ---- untrusted text ----


def test_hostile_actor_and_request_text_is_cleaned() -> None:
    raw = json.loads((FIXTURES / "cloudtrail_authorize_sg_ingress.json").read_text())
    raw["detail"]["userIdentity"] = {
        "type": "AssumedRole",
        "arn": "arn:aws:sts::123456789012:assumed-role/Dev/ig​nore<!-- x -->  me",
    }
    raw["detail"]["requestParameters"]["description"] = "A" * 5000
    raw["detail"]["requestParameters"]["secretAccessKey"] = "abc"
    event = parse_event(raw)
    assert event is not None
    assert event.context.actor == "assumed-role/Dev/ignore me"
    assert len(json.dumps(event.context.request)) < 2500
    assert event.context.request["secretAccessKey"] == "[redacted]"


# ---- attaching to findings ----


def test_s3_event_attaches_to_the_bucket_policy_finding() -> None:
    plan = plan_for(
        "aws_s3_bucket_policy", "aws_s3_bucket_policy.data",
        {"bucket": "acme-data", "policy": "{}"}, {"bucket": "acme-data", "policy": '{"a":1}'},
    )  # fmt: skip
    findings, resources = findings_for(plan)
    attach_event_context(findings, [], resources, events("cloudtrail_put_bucket_policy.json"))
    [f] = [f for f in findings if f.attribute_path == "policy"]
    assert f.change_context is not None
    assert f.change_context.actor == "assumed-role/PlatformAdmin/alice"
    assert f.change_context.event_name == "PutBucketPolicy"


def test_security_group_event_matches_by_group_id() -> None:
    plan = plan_for(
        "aws_security_group", "aws_security_group.admin",
        {"id": "sg-0abc123def4567890", "name": "admin"},
        {"id": "sg-0abc123def4567890", "name": "admin", "description": "x"},
    )  # fmt: skip
    findings, resources = findings_for(plan)
    attach_event_context(findings, [], resources, events("cloudtrail_authorize_sg_ingress.json"))
    assert findings and all(f.change_context.actor == "user/bob" for f in findings)


def test_other_resources_get_no_context() -> None:
    plan = plan_for(
        "aws_s3_bucket_policy", "aws_s3_bucket_policy.other",
        {"bucket": "someone-elses", "policy": "{}"}, {"bucket": "someone-elses", "policy": "[]"},
    )  # fmt: skip
    findings, resources = findings_for(plan)
    attach_event_context(findings, [], resources, events("cloudtrail_put_bucket_policy.json"))
    assert all(f.change_context is None for f in findings)


def test_latest_matching_event_wins() -> None:
    older = json.loads((FIXTURES / "cloudtrail_put_bucket_policy.json").read_text())
    newer = json.loads((FIXTURES / "cloudtrail_put_bucket_policy.json").read_text())
    older["detail"]["eventTime"] = "2026-11-19T01:00:00Z"
    older["detail"]["userIdentity"]["arn"] = "arn:aws:iam::123456789012:user/zed"
    older["detail"]["userIdentity"].pop("sessionContext")
    older["detail"]["userIdentity"]["type"] = "IAMUser"
    parsed = [e for raw in (newer, older) if (e := parse_event(raw))]
    plan = plan_for("aws_s3_bucket_policy", "aws_s3_bucket_policy.d", {"bucket": "acme-data"},
                    {"bucket": "acme-data", "policy": "x"})  # fmt: skip
    findings, resources = findings_for(plan)
    attach_event_context(findings, [], resources, parsed)
    assert findings[0].change_context.actor == "assumed-role/PlatformAdmin/alice"


def test_deleted_resource_matches_through_its_before_values() -> None:
    plan = plan_for("aws_cloudtrail", "aws_cloudtrail.main", {"name": "main"}, None,
                    actions=("delete",))  # fmt: skip
    findings, resources = findings_for(plan)
    attach_event_context(findings, [], resources, events("cloudtrail_stop_logging_raw.json"))
    assert findings[0].change_context.event_name == "StopLogging"


def test_unmanaged_resource_gets_the_creating_event() -> None:
    create = json.loads((FIXTURES / "cloudtrail_put_bucket_policy.json").read_text())
    create["detail"]["eventName"] = "CreateBucket"
    unmanaged = UnmanagedFinding(
        id="u1", run_id="r", detected_at=NOW, provider="aws", resource_kind="s3_bucket",
        resource_id="acme-data", name="acme-data",
    )  # fmt: skip
    attach_event_context([], [unmanaged], {}, [parse_event(create)])
    assert unmanaged.change_context.event_name == "CreateBucket"
