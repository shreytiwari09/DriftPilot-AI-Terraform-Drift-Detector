output "region" {
  value = local.region
}

output "demo_scope" {
  value = var.demo_scope
}

output "bucket_name" {
  description = "The demo S3 bucket (inject scenarios 20, 24, 25 and 26 act on it)."
  value       = aws_s3_bucket.demo.id
}

# The outputs below are null in the "s3" scope (those resources are not created there).
output "security_group_id" {
  description = "The database security group (inject scenario 21 acts on it). Full scope only."
  value       = one(aws_security_group.db[*].id)
}

output "db_identifier" {
  value = one(aws_db_instance.demo[*].identifier)
}

output "db_endpoint" {
  description = "Host name of the database. Full scope only."
  value       = one(aws_db_instance.demo[*].address)
}

output "db_port" {
  value = one(aws_db_instance.demo[*].port)
}

output "db_name" {
  value = one(aws_db_instance.demo[*].db_name)
}

output "db_username" {
  value = one(aws_db_instance.demo[*].username)
}

# Sensitive: hidden in normal output. Read it only when you need it:  terraform output -raw db_password
output "db_password" {
  description = "Master password of the database (also stored in the local state file). Full scope only."
  value       = one(random_password.db[*].result)
  sensitive   = true
}
