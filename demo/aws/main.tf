# DriftPilot real-AWS demo: one small S3 bucket, one security group and one small RDS Postgres.
# Prepared offline; nothing here is applied until you run `scripts/aws_demo.sh apply` (see README.md).
#
# Cost design: no NAT gateway, no load balancer, no EC2 instance, no Elastic IP, no Secrets Manager,
# no Multi-AZ, no Performance Insights, no enhanced monitoring. The only thing that bills by the hour is
# the one RDS instance (plus its 20 GB disk and its public IPv4 address). DESTROY IT AFTER THE DEMO.

locals {
  # Every resource carries these tags. The helper scripts and inject_drift.py only touch resources that have
  # demo=driftpilot, and `check-clean` looks for them to prove nothing is left.
  tags = {
    demo = "driftpilot"
    team = "platform"
  }
  name = "driftpilot-demo"
}

# A random suffix: S3 bucket names are global, so "driftpilot-demo" alone would already be taken.
resource "random_id" "suffix" {
  byte_length = 4
}

# The database's master password: generated here, kept in Terraform state (local, gitignored), never in a file
# you commit. No special characters so the password can go into a connection URL without escaping.
resource "random_password" "db" {
  length  = 24
  special = false
}

# ---------- S3 bucket: private, versioned, encrypted ----------

resource "aws_s3_bucket" "demo" {
  bucket        = "${local.name}-${random_id.suffix.hex}"
  force_destroy = true # `destroy` also removes any objects and old versions, so nothing is left billing
  tags          = local.tags
}

resource "aws_s3_bucket_public_access_block" "demo" {
  bucket                  = aws_s3_bucket.demo.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "demo" {
  bucket = aws_s3_bucket.demo.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "demo" {
  bucket = aws_s3_bucket.demo.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3: free, keys managed by S3
    }
  }
}

# ---------- Network: the default VPC, one security group ----------

# Every AWS account has a "default VPC" (a ready-made private network) in each region. Using it means no new
# subnets, route tables or gateways to pay for. If you deleted yours, see README.md.
data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "DriftPilot demo: PostgreSQL from one address only"
  vpc_id      = data.aws_vpc.default.id
  tags        = local.tags

  # Inline rule on purpose: DriftPilot's rule "admin port open to the world" looks at this block.
  ingress {
    description = "PostgreSQL from my laptop only"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.my_ip_cidr]
  }
}

# ---------- RDS: one small PostgreSQL 16, single-AZ ----------

# No aws_db_subnet_group: without one, RDS uses the default VPC's own "default" subnet group.
resource "aws_db_instance" "demo" {
  identifier = "${local.name}-db"

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "appdb"
  username = var.db_username
  password = random_password.db.result
  port     = 5432

  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = var.db_publicly_accessible
  multi_az               = false

  backup_retention_period      = 1 # the smallest value that keeps backups on (scenario 22 sets it to 0)
  deletion_protection          = false
  skip_final_snapshot          = true # no snapshot is left behind to bill you after destroy
  delete_automated_backups     = true
  performance_insights_enabled = false
  monitoring_interval          = 0     # no enhanced monitoring
  auto_minor_version_upgrade   = false # a surprise upgrade would show up as drift
  apply_immediately            = true

  tags = local.tags
}

# ---------- Optional spending alert ----------

resource "aws_budgets_budget" "guard" {
  count = var.enable_budget_guard ? 1 : 0

  name         = "${local.name}-guard"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_types {
    include_credit = false # count spend BEFORE credits, so the alert fires even while credits pay the bill
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  tags = local.tags
}
