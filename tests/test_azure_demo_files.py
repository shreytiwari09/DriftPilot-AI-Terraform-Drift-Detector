"""Static checks on demo/azure: the cost and safety rules hold in the files (nothing is run)."""

import re
import subprocess
from pathlib import Path

from driftpilot.config import load_config

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "demo" / "azure"
MAIN = (DEMO / "main.tf").read_text()
VARIABLES = (DEMO / "variables.tf").read_text()
VERSIONS = (DEMO / "versions.tf").read_text()


def block(kind: str) -> str:
    found = re.search(rf'resource "{kind}" "\w+" \{{(.*?)\n\}}\n', MAIN, flags=re.S)
    assert found, kind
    return found.group(1)


def test_only_the_three_demo_resources_and_the_random_suffix_exist() -> None:
    types = set(re.findall(r'^resource "(\w+)"', MAIN, flags=re.M))
    assert types == {
        "random_id",
        "azurerm_resource_group",
        "azurerm_storage_account",
        "azurerm_network_security_group",
    }
    assert not re.search(r'^(data|module) "', MAIN, flags=re.M)  # no lookups, no modules


def test_nothing_that_bills_by_the_hour_or_holds_secrets() -> None:
    for banned in (
        "virtual_machine",
        "public_ip",
        "key_vault",
        "sql",
        "postgresql",
        "kubernetes",
        "nat_gateway",
        "firewall",
        "bastion",
        "managed_disk",
        "cosmosdb",
    ):
        assert not re.search(rf'^resource "\w*{banned}\w*"', MAIN, flags=re.M), banned


def test_storage_account_is_small_private_and_named_right() -> None:
    sa = block("azurerm_storage_account")
    assert 'name                = "dpdemo${random_id.suffix.hex}"' in sa
    for line in (
        'account_tier             = "Standard"',
        'account_replication_type = "LRS"',
        'account_kind             = "StorageV2"',
        "https_traffic_only_enabled      = true",
        'min_tls_version                 = "TLS1_2"',
        "allow_nested_items_to_be_public = false",
        "tags                = local.tags",
    ):
        assert line in sa, line
    assert "byte_length = 4" in block("random_id")  # "dpdemo" + 8 hex characters = 14 <= 24


def test_every_resource_that_can_be_tagged_carries_the_demo_tag() -> None:
    assert 'demo = "driftpilot"' in MAIN and 'team = "platform"' in MAIN
    for kind in (
        "azurerm_resource_group",
        "azurerm_storage_account",
        "azurerm_network_security_group",
    ):
        assert "tags" in block(kind) and "local.tags" in block(kind), kind


def test_resource_group_name_matches_what_check_clean_looks_for() -> None:
    assert 'name     = "rg-driftpilot-demo-${random_id.suffix.hex}"' in block(
        "azurerm_resource_group"
    )
    assert 'RG_PREFIX="rg-driftpilot-demo-"' in (ROOT / "scripts" / "azure_demo.sh").read_text()


def test_the_nsg_has_one_ssh_rule_from_the_variable_only() -> None:
    nsg = block("azurerm_network_security_group")
    assert len(re.findall(r"security_rule \{", nsg)) == 1
    assert "source_address_prefix      = var.my_ip_cidr" in nsg
    assert 'destination_port_range     = "22"' in nsg
    assert "0.0.0.0/0" not in MAIN  # the only mention is the variable's rejection message


def test_my_ip_cidr_is_required_and_rejects_the_whole_internet() -> None:
    var = re.search(r'variable "my_ip_cidr" \{.*?\n\}\n', VARIABLES, flags=re.S).group(0)
    assert "default" not in var  # no default: nobody gets an open or empty rule by accident
    assert 'endswith(var.my_ip_cidr, "/32")' in var
    assert '"0.0.0.0/0", "*"' in var


def test_location_is_a_variable_with_a_cheap_default() -> None:
    var = re.search(r'variable "location" \{.*?\n\}\n', VARIABLES, flags=re.S).group(0)
    assert 'default     = "koreacentral"' in var
    for region in (
        "koreacentral",
        "indiasouthcentral",
        "eastasia",
        "malaysiawest",
        "indonesiacentral",
    ):
        assert region in var, region  # the subscription policy's allowed list
    assert "centralindia" not in var.replace("koreacentral", "")
    assert "var.location" in MAIN


def test_provider_is_pinned_and_takes_no_credentials() -> None:
    assert 'version = "~> 4.0"' in VERSIONS
    assert "client_secret" not in VERSIONS and "access_key" not in VERSIONS
    assert 'resource_provider_registrations = "none"' in VERSIONS
    assert '["Microsoft.Storage", "Microsoft.Network"]' in VERSIONS  # only what the demo needs


def test_lock_file_is_committed_and_secrets_and_state_are_ignored() -> None:
    assert (DEMO / ".terraform.lock.hcl").exists()
    tracked = subprocess.run(
        ["git", "ls-files", "demo/azure"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    for secret in ("terraform.tfvars\n", ".tfstate", ".demo.plan", ".terraform/"):
        assert secret not in tracked.replace("terraform.tfvars.example", "")
    for path in ("terraform.tfvars", "terraform.tfstate", ".demo.plan", ".terraform/x"):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", f"demo/azure/{path}"], cwd=ROOT
        ).returncode
        assert ignored == 0, path


def test_example_tfvars_has_only_placeholders() -> None:
    text = (DEMO / "terraform.tfvars.example").read_text()
    assert 'my_ip_cidr = "203.0.113.7/32"' in text  # a documentation address (RFC 5737)
    assert not re.search(r"(secret|password|key)\s*=", text, flags=re.I)


def test_offline_terraform_test_mocks_the_provider() -> None:
    text = (DEMO / "tests" / "scope.tftest.hcl").read_text()
    assert 'mock_provider "azurerm"' in text  # no Azure call, no login
    assert "expect_failures = [var.my_ip_cidr]" in text


def test_driftpilot_config_loads_and_has_no_secrets() -> None:
    config = load_config(None, DEMO)
    assert config.mode == "advise" and config.ownership.repo == "demo/azure"
    assert not re.search(r"(secret|password|token)\s*:", (DEMO / ".driftpilot.yml").read_text())


def test_runbook_covers_the_five_hand_changes_with_portal_and_cli() -> None:
    runbook = (DEMO / "RUNBOOK.md").read_text()
    for title in ("a)", "b)", "c)", "d)", "e)"):
        assert f"### {title}" in runbook, title
    for command in (
        "az storage account update",
        "az network nsg rule create",
        "--allow-blob-public-access",
        "--https-only",
        "--min-tls-version",
    ):
        assert command in runbook, command
    assert "If apply is denied by an Azure Policy" in (DEMO / "README.md").read_text()
