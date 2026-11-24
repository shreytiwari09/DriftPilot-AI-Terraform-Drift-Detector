"""Azure rules in the default pack: severities, tags, never-soften and the NSG predicate."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from driftpilot.collector import parse_plan, resource_values
from driftpilot.triage.rules import apply_rules, load_never_soften, load_rules, never_soften_for

NOW = datetime(2026, 11, 24, tzinfo=UTC)
RULES = load_rules()
NEVER = load_never_soften()
FIXTURES = Path(__file__).parent / "fixtures" / "azure"


def from_plan(plan: dict):
    findings = parse_plan(plan, "r", NOW)
    verdicts = apply_rules(findings, RULES, resource_values(plan))
    return findings, verdicts, resource_values(plan)


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def decide(type_: str, before, after, actions=("update",)):
    change = {"actions": list(actions), "before": before, "after": after}
    plan = {
        "resource_drift": [
            {"address": f"{type_}.x", "type": type_, "provider_name": "p", "change": change}
        ]
    }
    findings, verdicts, resources = from_plan(plan)
    return {f.attribute_path: (f, verdicts.get(f.id), resources[f.address]) for f in findings}


def rule(address_type: str, nsg_rules_before: list, nsg_rules_after: list):
    return decide(
        address_type, {"security_rule": nsg_rules_before}, {"security_rule": nsg_rules_after}
    )


def nsg_rule(source="203.0.113.7/32", port="22", **over) -> dict:
    base = {
        "name": "ssh",
        "direction": "Inbound",
        "access": "Allow",
        "protocol": "Tcp",
        "source_address_prefix": source,
        "source_address_prefixes": [],
        "destination_port_range": port,
        "destination_port_ranges": [],
    }
    return {**base, **over}


# ---- The plan fixture: every hand change of the runbook in one plan ----


def test_portal_changes_fixture_gives_the_expected_verdicts() -> None:
    findings, verdicts, _ = from_plan(fixture("portal_changes.json"))
    by_attr = {f.attribute_path: verdicts.get(f.id) for f in findings}
    assert set(by_attr) == {
        "allow_nested_items_to_be_public",
        "https_traffic_only_enabled",
        "min_tls_version",
        "tags.team",
        "security_rule",
    }
    expected = {
        "allow_nested_items_to_be_public": ("critical", "revert", ["public-storage"]),
        "https_traffic_only_enabled": ("critical", "revert", ["encryption-at-rest"]),
        "min_tls_version": ("high", "revert", ["encryption-at-rest"]),
        "tags.team": ("low", "codify", []),
        "security_rule": ("critical", "revert", ["network-exposure"]),
    }
    for attr, (severity, action, controls) in expected.items():
        v = by_attr[attr]
        assert (v.severity, v.recommended_action, v.controls, v.source) == (
            severity,
            action,
            controls,
            "rule",
        ), attr


def test_portal_changes_fixture_hides_the_secrets() -> None:
    plan = fixture("portal_changes.json")
    findings, _, resources = from_plan(plan)
    text = json.dumps([f.model_dump(mode="json") for f in findings]) + json.dumps(resources)
    assert "REDACTED-BY-TERRAFORM-SENSITIVE" not in text


def test_never_soften_covers_every_critical_finding_of_the_fixture() -> None:
    findings, verdicts, resources = from_plan(fixture("portal_changes.json"))
    for f in findings:
        v = verdicts[f.id]
        entry = never_soften_for(f, NEVER, resources.get(f.address))
        assert (entry is not None) == (v.severity == "critical"), f.attribute_path
        if entry:
            assert entry.floor_severity == "critical" and entry.controls == v.controls


def test_widening_the_source_of_the_ssh_rule_is_critical() -> None:
    findings, verdicts, resources = from_plan(fixture("nsg_ssh_source_widened.json"))
    [f] = findings
    assert f.attribute_path == "security_rule[0].source_address_prefix"
    assert verdicts[f.id].severity == "critical"
    assert never_soften_for(f, NEVER, resources[f.address]) is not None


def test_a_plan_without_drift_has_no_findings() -> None:
    assert parse_plan(fixture("no_drift.json"), "r", NOW) == []


# ---- Storage account ----


@pytest.mark.parametrize(
    ("attr", "before", "after", "control"),
    [
        ("allow_nested_items_to_be_public", False, True, "public-storage"),
        ("https_traffic_only_enabled", True, False, "encryption-at-rest"),
        ("enable_https_traffic_only", True, False, "encryption-at-rest"),  # azurerm 3.x name
        ("public_network_access_enabled", False, True, "network-exposure"),
    ],
)
def test_storage_account_opened_up_is_critical_and_never_softened(attr, before, after, control):
    f, v, resource = decide("azurerm_storage_account", {attr: before}, {attr: after})[attr]
    assert (v.severity, v.recommended_action, v.controls) == ("critical", "revert", [control])
    assert never_soften_for(f, NEVER, resource).floor_severity == "critical"


@pytest.mark.parametrize(
    ("attr", "before", "after"),
    [
        ("allow_nested_items_to_be_public", True, False),
        ("https_traffic_only_enabled", False, True),
        ("public_network_access_enabled", True, False),
    ],
)
def test_storage_account_tightened_is_not_a_critical_rule(attr, before, after) -> None:
    f, v, _ = decide("azurerm_storage_account", {attr: before}, {attr: after})[attr]
    assert v is None  # left to the AI / "needs triage"
    assert never_soften_for(f, NEVER) is None


def test_public_network_access_on_other_azure_resources_is_critical_too() -> None:
    _, v, _ = decide(
        "azurerm_key_vault",
        {"public_network_access_enabled": False},
        {"public_network_access_enabled": True},
    )["public_network_access_enabled"]
    assert v.severity == "critical"


@pytest.mark.parametrize("tls", ["TLS1_0", "TLS1_1"])
def test_lowered_minimum_tls_is_high(tls: str) -> None:
    f, v, _ = decide(
        "azurerm_storage_account", {"min_tls_version": "TLS1_2"}, {"min_tls_version": tls}
    )["min_tls_version"]
    assert (v.severity, v.recommended_action, v.controls) == (
        "high",
        "revert",
        ["encryption-at-rest"],
    )
    assert never_soften_for(f, NEVER) is None  # high, not on the critical never-soften list


def test_raised_minimum_tls_is_not_a_rule() -> None:
    _, v, _ = decide(
        "azurerm_storage_account", {"min_tls_version": "TLS1_0"}, {"min_tls_version": "TLS1_2"}
    )["min_tls_version"]
    assert v is None


@pytest.mark.parametrize("type_", ["azurerm_storage_account", "azurerm_network_security_group"])
def test_tag_edit_is_low(type_: str) -> None:
    out = decide(type_, {"tags": {"team": "platform"}}, {"tags": {"team": "data", "cost": "1"}})
    for attr in ("tags.team", "tags.cost"):
        _, v, _ = out[attr]
        assert (v.severity, v.recommended_action, v.is_real_drift) == ("low", "codify", True)


def test_removed_tag_is_low_and_still_real() -> None:
    _, v, _ = decide("azurerm_resource_group", {"tags": {"demo": "driftpilot"}}, {"tags": {}})[
        "tags.demo"
    ]
    assert (v.severity, v.is_real_drift) == ("low", True)


# ---- Network security group ----


def test_added_open_ssh_rule_is_critical() -> None:
    out = rule("azurerm_network_security_group", [nsg_rule()], [nsg_rule(), nsg_rule("*")])
    f, v, resource = out["security_rule"]
    assert (v.severity, v.controls, v.rule_id) == (
        "critical",
        ["network-exposure"],
        "azure-nsg-admin-port-open",
    )
    assert never_soften_for(f, NEVER, resource).floor_severity == "critical"


@pytest.mark.parametrize("source", ["*", "0.0.0.0/0", "Internet", "internet", "Any", "::/0"])
def test_every_way_of_saying_anywhere_counts(source: str) -> None:
    out = rule("azurerm_network_security_group", [nsg_rule()], [nsg_rule(source)])
    _, v, _ = out["security_rule[0].source_address_prefix"]
    assert v.severity == "critical"


def test_any_in_a_list_of_sources_counts() -> None:
    after = nsg_rule(source_address_prefix="", source_address_prefixes=["10.0.0.0/8", "*"])
    out = rule("azurerm_network_security_group", [nsg_rule()], [after])
    assert out["security_rule[0].source_address_prefix"][1].severity == "critical"


@pytest.mark.parametrize(
    "ports",
    [
        {"destination_port_range": "3389"},
        {"destination_port_range": "*"},
        {"destination_port_range": "20-30"},
        {"destination_port_range": "", "destination_port_ranges": ["80", "3380-3390"]},
    ],
)
def test_admin_ports_inside_ranges_count(ports: dict) -> None:
    out = rule("azurerm_network_security_group", [nsg_rule()], [nsg_rule(), nsg_rule("*", **ports)])
    assert out["security_rule"][1].severity == "critical"


@pytest.mark.parametrize(
    "benign",
    [
        {"destination_port_range": "443"},  # not an admin port
        {"destination_port_range": "8000-9000"},
        {"access": "Deny"},  # a block rule
        {"direction": "Outbound"},
        {"protocol": "Udp"},
    ],
)
def test_open_rules_that_are_not_an_admin_exposure_are_not_critical(benign: dict) -> None:
    out = rule(
        "azurerm_network_security_group", [nsg_rule()], [nsg_rule(), nsg_rule("*", **benign)]
    )
    assert out["security_rule"][1] is None


def test_a_rule_from_one_address_is_not_critical() -> None:
    out = rule(
        "azurerm_network_security_group", [nsg_rule()], [nsg_rule(), nsg_rule("198.51.100.9/32")]
    )
    assert out["security_rule"][1] is None


def test_standalone_nsg_rule_resource_is_checked_too() -> None:
    f, v, _ = decide("azurerm_network_security_rule", nsg_rule(), nsg_rule("*"))[
        "source_address_prefix"
    ]
    assert v.severity == "critical"
    assert never_soften_for(f, NEVER, nsg_rule("*")) is not None


# ---- Pack hygiene ----


def test_azure_never_soften_entries_are_critical_and_have_tags() -> None:
    azure = [e for e in NEVER if e.type.startswith("azurerm_")]
    assert len(azure) == 4
    assert all(e.floor_severity == "critical" and e.controls for e in azure)


def test_azure_rule_ids_are_unique_and_prefixed() -> None:
    ids = [r.id for r in RULES if r.match.type.startswith("azurerm_")]
    assert len(ids) == len(set(ids)) == 7 and all(i.startswith("azure-") for i in ids)


# ---- The scan command on a recorded Azure plan (no Azure, no Terraform) ----


def test_scan_command_replays_the_azure_plan_with_the_demo_config() -> None:
    from typer.testing import CliRunner

    from driftpilot.cli import app

    demo = Path(__file__).parents[1] / "demo" / "azure"
    args = ["scan", "--dir", str(demo), "--no-llm", "--json"]
    result = CliRunner().invoke(app, [*args, "--plan-json", str(FIXTURES / "portal_changes.json")])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    severities = sorted(v["severity"] for v in data["verdicts"].values())
    assert severities == ["critical", "critical", "critical", "high", "low"]
    clean = CliRunner().invoke(app, [*args, "--plan-json", str(FIXTURES / "no_drift.json")])
    assert clean.exit_code == 0 and json.loads(clean.stdout)["findings"] == []
