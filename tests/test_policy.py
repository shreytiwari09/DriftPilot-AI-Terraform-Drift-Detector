from datetime import UTC, datetime

import pytest

from driftpilot.config import Config
from driftpilot.models import DriftFinding, UnmanagedFinding, Verdict
from driftpilot.triage.policy import apply_policy, plan_remediations, resolve_action

NOW = datetime(2026, 10, 25, tzinfo=UTC)


def finding(fid: str, address: str = "docker_container.web", attr: str = "memory") -> DriftFinding:
    return DriftFinding(
        id=fid,
        run_id="r",
        detected_at=NOW,
        provider="p",
        resource_type=address.split(".")[0],
        address=address,
        change_kind="modified",
        attribute_path=attr,
        before=1,
        after=2,
    )


def verdict(fid: str, action="codify", severity="medium", confidence=0.9) -> Verdict:
    return Verdict(
        finding_id=fid,
        source="llm",
        is_real_drift=True,
        severity=severity,
        category="availability",
        intent="likely_hotfix",
        recommended_action=action,
        confidence=confidence,
        reason="r",
    )


def test_low_confidence_becomes_investigate() -> None:
    out = apply_policy([finding("a")], [], {"a": verdict("a", confidence=0.5)}, Config())
    assert (out["a"].recommended_action, out["a"].source) == ("investigate", "policy")
    assert "below 0.7" in out["a"].reason


def test_config_ignore_and_severity_override() -> None:
    config = Config.model_validate(
        {
            "ignore": ["docker_container.*.restart"],
            "severity_overrides": [
                {"match": {"type": "docker_container", "attribute": "memory"}, "severity": "low"}
            ],
        }
    )
    fs = [finding("a", attr="restart"), finding("b", attr="memory")]
    out = apply_policy(fs, [], {"a": verdict("a"), "b": verdict("b")}, config)
    assert out["a"].is_real_drift is False
    assert out["b"].severity == "low"


def test_unmanaged_gets_import_verdict() -> None:
    u = UnmanagedFinding(
        id="u",
        run_id="r",
        detected_at=NOW,
        provider="p",
        resource_kind="repository",
        resource_id="1",
        name="demo-handmade",
    )
    out = apply_policy([], [u], {}, Config())
    assert (out["u"].recommended_action, out["u"].source) == ("import", "policy")


@pytest.mark.parametrize(
    ("actions", "expected"),
    [
        (["codify", "codify"], "codify"),
        (["codify", "revert"], "revert"),
        (["recreate"], "recreate"),
        (["codify", "investigate"], "investigate"),
        (["codify", "ignore_changes"], "investigate"),
    ],
)
def test_resolve_action(actions, expected) -> None:
    assert resolve_action(actions) == expected


def test_one_plan_per_resource_and_delivery_rules() -> None:
    fs = [
        finding("a", "docker_container.web", "restart"),
        finding("b", "docker_container.web", "max_retry_count"),
        finding("c", "github_branch_protection.api_main", "required_status_checks"),
        finding("d", "github_repository.api", "description"),
    ]
    verdicts = {
        "a": verdict("a", "investigate"),
        "b": verdict("b", "codify"),
        "c": verdict("c", "codify", "critical"),
        "d": verdict("d", "codify", "low"),
    }
    plans = {p.address: p for p in plan_remediations(fs, [], verdicts, Config(mode="open-prs"))}
    assert (plans["docker_container.web"].action, plans["docker_container.web"].delivery) == (
        "investigate",
        "issue",
    )
    assert plans["docker_container.web"].finding_ids == ["a", "b"]
    # critical codify still goes to a human as an issue
    assert plans["github_branch_protection.api_main"].delivery == "issue"
    assert plans["github_repository.api"].delivery == "pr"
    assert plans["github_repository.api"].key == "codify:github_repository.api"


def test_advise_mode_never_opens_prs() -> None:
    plans = plan_remediations([finding("d")], [], {"d": verdict("d")}, Config())
    assert plans[0].delivery == "issue"


def test_noise_is_not_planned() -> None:
    v = verdict("a").model_copy(update={"is_real_drift": False, "recommended_action": "none"})
    assert plan_remediations([finding("a")], [], {"a": v}, Config(mode="open-prs")) == []
