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

  # Do not let Terraform register its usual long list of Azure services: a student subscription may not allow it.
  # Register only the two the demo needs. A service that is already registered is left alone; if it is not, the
  # first plan or apply registers it (free, one time). You can also do it yourself: README.md, "Before you start".
  resource_provider_registrations = "none"
  resource_providers_to_register  = ["Microsoft.Storage", "Microsoft.Network"]

  # No passwords or keys here: Terraform uses your `az login` session. See README.md.
}
