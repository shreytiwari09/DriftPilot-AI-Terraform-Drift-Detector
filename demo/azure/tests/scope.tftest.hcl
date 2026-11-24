# Offline check of the whole demo: a mocked Azure provider, so no Azure call and no login.
#   terraform -chdir=demo/azure init -backend=false && terraform -chdir=demo/azure test

mock_provider "azurerm" {}

mock_provider "random" {}

# The random suffix is only known after apply; fix it so the names can be checked in a plan.
override_resource {
  target          = random_id.suffix
  override_during = plan
  values = {
    hex = "a1b2c3d4"
  }
}

# Every run sets its own values, so a local terraform.tfvars (auto-loaded) cannot change the result.
run "creates_only_the_three_demo_resources" {
  command = plan

  variables {
    location        = "centralindia"
    subscription_id = ""
    my_ip_cidr      = "198.51.100.9/32"
  }

  assert {
    condition     = azurerm_resource_group.demo.name == "rg-driftpilot-demo-a1b2c3d4" && azurerm_resource_group.demo.location == "centralindia"
    error_message = "the resource group name must start with rg-driftpilot-demo- (check-clean looks for it)"
  }
  assert {
    condition     = azurerm_storage_account.demo.name == "dpdemoa1b2c3d4" && length(azurerm_storage_account.demo.name) <= 24 && azurerm_storage_account.demo.name == lower(azurerm_storage_account.demo.name)
    error_message = "the storage account name must be dpdemo + suffix, lowercase, at most 24 characters"
  }
  assert {
    condition     = azurerm_storage_account.demo.account_tier == "Standard" && azurerm_storage_account.demo.account_replication_type == "LRS" && azurerm_storage_account.demo.account_kind == "StorageV2"
    error_message = "the storage account must be Standard, LRS, StorageV2 (the cheapest)"
  }
  assert {
    condition     = azurerm_storage_account.demo.https_traffic_only_enabled == true && azurerm_storage_account.demo.min_tls_version == "TLS1_2" && azurerm_storage_account.demo.allow_nested_items_to_be_public == false
    error_message = "https only, TLS 1.2 and no anonymous blob access must be on in the code"
  }
  assert {
    condition     = azurerm_storage_account.demo.tags["demo"] == "driftpilot" && azurerm_storage_account.demo.tags["team"] == "platform" && azurerm_resource_group.demo.tags["demo"] == "driftpilot" && azurerm_network_security_group.demo.tags["demo"] == "driftpilot"
    error_message = "every resource must carry demo=driftpilot and team=platform"
  }
  assert {
    condition     = length(azurerm_network_security_group.demo.security_rule) == 1
    error_message = "the network security group must have exactly one rule"
  }
  assert {
    condition     = one(azurerm_network_security_group.demo.security_rule).source_address_prefix == "198.51.100.9/32" && one(azurerm_network_security_group.demo.security_rule).destination_port_range == "22" && one(azurerm_network_security_group.demo.security_rule).access == "Allow" && one(azurerm_network_security_group.demo.security_rule).direction == "Inbound"
    error_message = "the one rule must allow SSH (22) from my_ip_cidr only"
  }
}

run "location_can_be_changed" {
  command = plan

  variables {
    location        = "southeastasia"
    subscription_id = ""
    my_ip_cidr      = "198.51.100.9/32"
  }

  assert {
    condition     = azurerm_resource_group.demo.location == "southeastasia" && azurerm_storage_account.demo.location == "southeastasia" && azurerm_network_security_group.demo.location == "southeastasia"
    error_message = "everything must follow var.location"
  }
}

run "a_display_name_is_not_a_location" {
  command = plan

  variables {
    location        = "Central India"
    subscription_id = ""
    my_ip_cidr      = "198.51.100.9/32"
  }

  expect_failures = [var.location]
}

run "the_whole_internet_is_rejected" {
  command = plan

  variables {
    location        = "centralindia"
    subscription_id = ""
    my_ip_cidr      = "0.0.0.0/0"
  }

  expect_failures = [var.my_ip_cidr]
}

run "a_star_is_rejected" {
  command = plan

  variables {
    location        = "centralindia"
    subscription_id = ""
    my_ip_cidr      = "*"
  }

  expect_failures = [var.my_ip_cidr]
}

run "a_wider_range_than_one_address_is_rejected" {
  command = plan

  variables {
    location        = "centralindia"
    subscription_id = ""
    my_ip_cidr      = "198.51.100.0/24"
  }

  expect_failures = [var.my_ip_cidr]
}

run "a_malformed_subscription_id_is_rejected" {
  command = plan

  variables {
    location        = "centralindia"
    subscription_id = "not-a-guid"
    my_ip_cidr      = "198.51.100.9/32"
  }

  expect_failures = [var.subscription_id]
}
