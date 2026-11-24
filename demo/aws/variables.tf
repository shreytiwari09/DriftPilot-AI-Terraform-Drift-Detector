variable "region" {
  description = "AWS region for everything in this demo (ap-south-1 is Mumbai). The helper scripts and IAM policies assume this region."
  type        = string
  default     = "ap-south-1"
}

variable "my_ip_cidr" {
  description = "Your public IP address as a /32 (for example 203.0.113.7/32). Only this address may reach the database on port 5432."
  type        = string

  validation {
    condition     = can(cidrhost(var.my_ip_cidr, 0)) && endswith(var.my_ip_cidr, "/32")
    error_message = "my_ip_cidr must be a single IPv4 address written as a /32, for example 203.0.113.7/32."
  }

  validation {
    condition     = var.my_ip_cidr != "0.0.0.0/0"
    error_message = "0.0.0.0/0 would open the database to the whole internet. Use your own address as a /32."
  }
}

variable "db_instance_class" {
  description = "RDS instance size. db.t4g.micro is the smallest class that runs PostgreSQL 16 (verify against the RDS pricing page)."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_publicly_accessible" {
  description = "Whether the database gets a public address. True so your laptop can reach it; the security group still limits who can connect to your /32."
  type        = bool
  default     = true
}

variable "db_username" {
  description = "Name of the database's master (owner) login. The password is generated, not set here."
  type        = string
  default     = "appowner"
}

variable "enable_budget_guard" {
  description = "Create an AWS Budgets alert at budget_limit_usd. Off by default; AWS Budgets' first budgets are free (check the Budgets pricing page)."
  type        = bool
  default     = false
}

variable "budget_limit_usd" {
  description = "Monthly spend (before credits are applied) that triggers the email alert."
  type        = number
  default     = 20
}

variable "budget_email" {
  description = "Where the budget alert is sent. Only used when enable_budget_guard is true. Put it in terraform.tfvars, never in a committed file."
  type        = string
  default     = ""

  validation {
    condition     = var.budget_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_email))
    error_message = "budget_email must be an email address (or left empty)."
  }
}
