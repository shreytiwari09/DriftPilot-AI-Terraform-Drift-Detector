output "location" {
  value = var.location
}

output "resource_group_name" {
  description = "The resource group that holds the whole demo."
  value       = azurerm_resource_group.demo.name
}

output "storage_account_name" {
  description = "The demo storage account (RUNBOOK.md scenarios a, b, c and e change it by hand)."
  value       = azurerm_storage_account.demo.name
}

output "network_security_group_name" {
  description = "The demo network security group (RUNBOOK.md scenario d adds a rule to it)."
  value       = azurerm_network_security_group.demo.name
}
