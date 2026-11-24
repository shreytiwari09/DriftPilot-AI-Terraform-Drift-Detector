terraform {
  required_version = ">= 1.5"

  required_providers {
    # Pinned to a major version so a new release cannot change the demo under you.
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = local.region

  # Credentials are NOT written here. Terraform reads them from the profile you export
  # (AWS_PROFILE=driftpilot-demo), the same way the AWS CLI does. See README.md.
}
