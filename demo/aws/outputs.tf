output "region" {
  value = var.region
}

output "bucket_name" {
  description = "The demo S3 bucket (inject scenarios 20 and 24 act on it)."
  value       = aws_s3_bucket.demo.id
}

output "security_group_id" {
  description = "The database security group (inject scenario 21 acts on it)."
  value       = aws_security_group.db.id
}

output "db_identifier" {
  value = aws_db_instance.demo.identifier
}

output "db_endpoint" {
  description = "Host name of the database."
  value       = aws_db_instance.demo.address
}

output "db_port" {
  value = aws_db_instance.demo.port
}

output "db_name" {
  value = aws_db_instance.demo.db_name
}

output "db_username" {
  value = aws_db_instance.demo.username
}

# Sensitive: hidden in normal output. Read it only when you need it:  terraform output -raw db_password
output "db_password" {
  description = "Master password of the database (also stored in the local state file)."
  value       = random_password.db.result
  sensitive   = true
}
