terraform {
  required_version = ">= 1.5"

  required_providers {
    # Pinned to a major version so a new release cannot change the demo under you.
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}

  # Which subscription to use. Empty: Terraform takes the one `az login` is using (scripts/azure_demo.sh
  # exports it as ARM_SUBSCRIPTION_ID, so the script and Terraform always agree).
  subscription_id = var.subscription_id != "" ? var.subscription_id : null

  # Do not let Terraform try to register a long list of Azure services on its own: a student subscription may
  # not allow it. Storage and Network are normally registered already (README.md, "Before you start").
  resource_provider_registrations = "none"

  # No passwords or keys here: Terraform uses your `az login` session. See README.md.
}
