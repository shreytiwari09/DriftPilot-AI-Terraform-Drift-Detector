# DriftPilot real-Azure demo: one resource group, one storage account, one network security group. Nothing else.
# Prepared offline; nothing here is applied until you run `scripts/azure_demo.sh apply` (see README.md).
#
# Cost design: no virtual machine, no public IP address, no database, no Key Vault, no gateway, no disk.
# A resource group and a network security group are free; an empty Standard LRS storage account costs a
# fraction of a cent. DESTROY IT AFTER THE DEMO.

locals {
  # Every resource carries these tags. check-clean looks for the resource group name prefix, and the runbook
  # edits the "team" tag on purpose to show a harmless drift.
  tags = {
    demo = "driftpilot"
    team = "platform"
  }
}

# A random suffix: storage account names are global (everybody in the world shares them) and may only hold
# 3 to 24 lowercase letters and digits, so "dpdemo" alone would already be taken.
resource "random_id" "suffix" {
  byte_length = 4 # 8 hex characters, always lowercase
}

# A resource group is a folder that holds everything the demo creates. Deleting it deletes all of it.
# The name starts with rg-driftpilot-demo- on purpose: `scripts/azure_demo.sh check-clean` looks for that.
resource "azurerm_resource_group" "demo" {
  name     = "rg-driftpilot-demo-${random_id.suffix.hex}"
  location = var.location
  tags     = local.tags
}

# ---------- Storage account: private, https only, TLS 1.2 or newer ----------

resource "azurerm_storage_account" "demo" {
  name                = "dpdemo${random_id.suffix.hex}" # 14 characters, lowercase letters and digits
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  tags                = local.tags

  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS" # the cheapest: three copies in one datacentre

  # The settings DriftPilot's Azure rules watch. Each one can be changed by hand in the portal (RUNBOOK.md).
  https_traffic_only_enabled      = true # "Secure transfer required"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false # "Allow Blob anonymous access" is OFF

  # public_network_access_enabled is left at its default (on): Terraform on your laptop must still be able to read
  # the account. Who may log in is decided by keys and by the settings above, and no container is created.
}

# ---------- Network security group: SSH from one address only ----------

# A network security group (NSG) is a firewall rule list. It is not attached to anything (there is no virtual
# network or machine in this demo), so it only exists to be watched. The rule is inline on purpose: DriftPilot's
# rule "admin port open to the world" looks at this block.
resource "azurerm_network_security_group" "demo" {
  name                = "nsg-driftpilot-demo"
  location            = azurerm_resource_group.demo.location
  resource_group_name = azurerm_resource_group.demo.name
  tags                = local.tags

  security_rule {
    name                       = "ssh-from-my-ip"
    description                = "SSH from my laptop only"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.my_ip_cidr
    destination_address_prefix = "*"
  }
}
