from datetime import UTC, datetime
from pathlib import Path

import pytest

from driftpilot.collector import parse_plan, resource_values
from driftpilot.triage.rules import apply_rules, load_rules

NOW = datetime(2026, 10, 25, tzinfo=UTC)
RULES = load_rules()


def triage(plan: dict) -> tuple[list, dict]:
    findings = parse_plan(plan, "r1", NOW)
    return findings, apply_rules(findings, RULES, resource_values(plan))


def rule_ids(plan: dict) -> dict[str | None, str | None]:
    findings, verdicts = triage(plan)
    return {f.attribute_path: (v.rule_id if (v := verdicts.get(f.id)) else None) for f in findings}


def one_change(type_: str, before, after, address: str = "x.y", actions=("update",)) -> dict:
    return {
        "resource_drift": [
            {
                "address": address,
                "type": type_,
                "provider_name": "p",
                "change": {"actions": list(actions), "before": before, "after": after},
            }
        ]
    }


# ---- Noise from recorded Phase 0 fixtures ----


@pytest.mark.parametrize(
    "fixture",
    ["docker/noise_provider_defaults_after_apply", "github/noise_provider_defaults_after_apply"],
)
def test_first_refresh_noise_is_all_filtered(load_fixture, fixture: str) -> None:
    findings, verdicts = triage(load_fixture(fixture))
    assert findings
    assert all(not verdicts[f.id].is_real_drift for f in findings)


def test_mac_address_change_is_noise(load_fixture) -> None:
    ids = rule_ids(load_fixture("docker/noise_mac_address_after_restart"))
    assert ids["network_data[0].mac_address"] == "noise-docker-network-data"


def test_etag_is_noise(load_fixture) -> None:
    ids = rule_ids(load_fixture("github/noise_provider_defaults_after_apply"))
    assert ids["etag"] == "noise-etag"


# ---- Real drift ----


def test_required_approvals_reduced_is_critical(load_fixture) -> None:
    findings, verdicts = triage(load_fixture("github/s2_required_approvals_reduced"))
    [v] = verdicts.values()
    assert (v.rule_id, v.severity, v.category, v.recommended_action) == (
        "github-required-approvals-reduced",
        "critical",
        "security",
        "revert",
    )
    assert v.source == "rule"


def test_required_approvals_increased_is_not_decided() -> None:
    plan = one_change(
        "github_branch_protection",
        {"required_pull_request_reviews": [{"required_approving_review_count": 1}]},
        {"required_pull_request_reviews": [{"required_approving_review_count": 3}]},
    )
    assert set(rule_ids(plan).values()) == {None}


def test_branch_protection_deleted_is_critical() -> None:
    plan = one_change("github_branch_protection", {"pattern": "main"}, None, actions=("delete",))
    assert rule_ids(plan) == {None: "github-branch-protection-deleted"}


def test_team_raised_to_admin_is_high() -> None:
    plan = one_change("github_team_repository", {"permission": "pull"}, {"permission": "admin"})
    findings, verdicts = triage(plan)
    [v] = verdicts.values()
    assert (v.rule_id, v.severity) == ("github-team-permission-admin", "high")


def test_ordinary_changes_need_triage(load_fixture) -> None:
    for fixture in [
        "docker/s11_memory_changed",
        "docker/s12_restart_policy_changed",
        "docker/s10_container_removed",
    ]:
        findings, verdicts = triage(load_fixture(fixture))
        assert findings and verdicts == {}, fixture


def test_live_batch_a(load_fixture) -> None:
    """Scenarios 2, 3, 5, 6, 7, 8 injected together on the real demo org."""
    ids = rule_ids(load_fixture("github/batch_a_s2_s3_s5_s6_s7_s8"))
    assert ids == {
        "required_pull_request_reviews[0].required_approving_review_count": (
            "github-required-approvals-reduced"
        ),
        "permission": "github-team-permission-admin",
        "etag": "noise-etag",
        "required_status_checks": None,
        "description": None,
        "has_issues": None,
        "topics": None,
    }


def test_live_batch_b(load_fixture) -> None:
    """Scenarios 1 and 4: protection deleted, demo-web archived (which also turns off alerts)."""
    findings, verdicts = triage(load_fixture("github/batch_b_s1_s4"))
    by_path = {(f.address, f.attribute_path): verdicts.get(f.id) for f in findings}
    assert by_path[("github_branch_protection.api_main", None)].severity == "critical"
    assert by_path[("github_repository.web", "archived")] is None
    assert by_path[("github_repository.web", "vulnerability_alerts")] is None


def test_list_reordered_and_json_equal_are_noise() -> None:
    assert rule_ids(
        one_change("github_repository", {"topics": ["a", "b"]}, {"topics": ["b", "a"]})
    ) == {"topics": "noise-list-reordered"}
    assert rule_ids(one_change("github_repository", {"topics": ["a"]}, {"topics": ["a", "c"]})) == {
        "topics": None
    }
    policy_before = '{"Version": "2012-10-17", "Statement": []}'
    policy_after = '{"Statement":[],"Version":"2012-10-17"}'
    assert rule_ids(
        one_change("aws_iam_policy", {"policy": policy_before}, {"policy": policy_after})
    ) == {"policy": "noise-json-equivalent"}


def _ingress(cidr: str, port: int) -> dict:
    return {"cidr_blocks": [cidr], "from_port": port, "to_port": port, "protocol": "tcp"}


def test_open_ssh_to_internet_is_critical() -> None:
    plan = one_change(
        "aws_security_group",
        {"ingress": [_ingress("10.0.0.0/8", 22)]},
        {"ingress": [_ingress("0.0.0.0/0", 22)]},
    )
    assert rule_ids(plan) == {"ingress[0].cidr_blocks": "open-cidr-on-admin-port"}


def test_open_https_to_internet_is_not_admin_port() -> None:
    plan = one_change(
        "aws_security_group",
        {"ingress": [_ingress("10.0.0.0/8", 443)]},
        {"ingress": [_ingress("0.0.0.0/0", 443)]},
    )
    assert rule_ids(plan) == {"ingress[0].cidr_blocks": None}


def test_unknown_predicate_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "rules.yaml"
    path.write_text(
        """
rules:
  - id: typo
    when: nul_to_default
    verdict: {is_real_drift: false, severity: none, category: cosmetic, intent: unknown,
              recommended_action: none, confidence: 1, reason: x}
"""
    )
    with pytest.raises(ValueError, match="unknown rule predicate"):
        load_rules(path)


# ---- Repository rulesets (found on the second repo, Cloud Posse module) ----


def test_live_ruleset_approvals_reduced_is_critical(load_fixture) -> None:
    ids = rule_ids(load_fixture("github/platform_ruleset_approvals_reduced"))
    assert ids["rules[0].pull_request[0].required_approving_review_count"] == (
        "github-ruleset-approvals-reduced"
    )


@pytest.mark.parametrize(
    ("before", "after", "rule"),
    [
        ({"enforcement": "active"}, {"enforcement": "disabled"}, "github-ruleset-disabled"),
        ({"enforcement": "active"}, {"enforcement": "evaluate"}, "github-ruleset-evaluate-only"),
        (
            {"rules": [{"deletion": True}]},
            {"rules": [{"deletion": False}]},
            "github-ruleset-deletion-allowed",
        ),
        (
            {"rules": [{"non_fast_forward": True}]},
            {"rules": [{"non_fast_forward": False}]},
            "github-ruleset-force-push-allowed",
        ),
    ],
)
def test_ruleset_weakening_rules(before, after, rule) -> None:
    address = 'module.billing.github_repository_ruleset.default["main"]'
    plan = one_change("github_repository_ruleset", before, after, address=address)
    assert list(rule_ids(plan).values()) == [rule]


def test_ruleset_deleted() -> None:
    plan = one_change("github_repository_ruleset", {"name": "x"}, None, actions=("delete",))
    assert rule_ids(plan) == {None: "github-ruleset-deleted"}
