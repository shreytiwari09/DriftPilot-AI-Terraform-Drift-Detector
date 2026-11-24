# Offline check of both scopes: a mocked AWS provider, so no AWS call and no credentials.
#   terraform -chdir=demo/aws init -backend=false && terraform -chdir=demo/aws test

mock_provider "aws" {
  mock_data "aws_vpc" {
    defaults = {
      id = "vpc-0123456789abcdef0"
    }
  }
}

mock_provider "random" {}

# Every run sets its own values, so a local terraform.tfvars (auto-loaded) cannot change the result.
run "s3_scope_creates_only_the_bucket" {
  command = plan

  variables {
    demo_scope = "s3"
    region     = ""
    my_ip_cidr = ""
  }

  assert {
    condition     = local.region == "us-east-1" && local.full == false
    error_message = "s3 scope must use us-east-1"
  }
  assert {
    condition     = length(aws_security_group.db) == 0 && length(aws_db_instance.demo) == 0 && length(data.aws_vpc.default) == 0 && length(random_password.db) == 0
    error_message = "s3 scope must not plan a VPC lookup, security group, database or password"
  }
  assert {
    condition     = length(aws_budgets_budget.guard) == 0
    error_message = "s3 scope has no budget"
  }
  assert {
    condition     = aws_s3_bucket.demo.tags["demo"] == "driftpilot"
    error_message = "the bucket must carry the demo tag"
  }
}

run "full_scope_adds_the_network_and_the_database" {
  command = plan

  variables {
    demo_scope = "full"
    region     = ""
    my_ip_cidr = "198.51.100.9/32"
  }

  assert {
    condition     = local.region == "ap-south-1"
    error_message = "full scope must use ap-south-1"
  }
  assert {
    condition     = length(aws_security_group.db) == 1 && length(aws_db_instance.demo) == 1 && length(data.aws_vpc.default) == 1
    error_message = "full scope must plan the security group and the database"
  }
}

run "full_scope_needs_an_ip" {
  command = plan

  variables {
    demo_scope = "full"
    region     = ""
    my_ip_cidr = ""
  }

  expect_failures = [aws_security_group.db]
}

run "the_scope_refuses_a_different_region" {
  command = plan

  variables {
    demo_scope = "s3"
    region     = "ap-south-1"
    my_ip_cidr = ""
  }

  expect_failures = [aws_s3_bucket.demo]
}

run "the_open_world_is_rejected" {
  command = plan

  variables {
    demo_scope = "full"
    region     = ""
    my_ip_cidr = "0.0.0.0/0"
  }

  expect_failures = [var.my_ip_cidr]
}
