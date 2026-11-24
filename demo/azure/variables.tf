variable "location" {
  description = "Azure region for everything. This subscription's Azure Policy \"Allowed resource deployment regions\" (set by Azure for Students, not by this demo) allows only koreacentral, indiasouthcentral, eastasia, malaysiawest and indonesiacentral, so only those are accepted here. See README.md."
  type        = string
  default     = "koreacentral"

  validation {
    condition     = contains(["koreacentral", "indiasouthcentral", "eastasia", "malaysiawest", "indonesiacentral"], var.location)
    error_message = "location must be one of the regions the subscription's Azure Policy allows: koreacentral, indiasouthcentral, eastasia, malaysiawest, indonesiacentral (short lowercase names, not \"Korea Central\")."
  }
}

variable "subscription_id" {
  description = "Id of the Azure subscription to use. Leave empty to use the one your `az login` session is on (scripts/azure_demo.sh does this for you)."
  type        = string
  default     = ""

  validation {
    condition     = var.subscription_id == "" || can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID such as 00000000-0000-0000-0000-000000000000 (or left empty)."
  }
}

variable "my_ip_cidr" {
  description = "Your public IP address as a /32 (for example 203.0.113.7/32). Only this address may reach port 22 (SSH) in the network security group. Put it in terraform.tfvars, which is gitignored."
  type        = string

  validation {
    condition     = can(cidrhost(var.my_ip_cidr, 0)) && endswith(var.my_ip_cidr, "/32")
    error_message = "my_ip_cidr must be a single IPv4 address written as a /32, for example 203.0.113.7/32."
  }

  validation {
    condition     = !contains(["0.0.0.0/0", "*", "Internet", "Any"], var.my_ip_cidr)
    error_message = "0.0.0.0/0, * and Internet would open SSH to the whole internet. Use your own address as a /32."
  }
}
