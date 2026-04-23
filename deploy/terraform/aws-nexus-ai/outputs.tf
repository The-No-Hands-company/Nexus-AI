output "vpc_id" {
  description = "Created VPC ID"
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = [for subnet in aws_subnet.public : subnet.id]
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = [for subnet in aws_subnet.private : subnet.id]
}

output "app_security_group_id" {
  description = "Application security group ID"
  value       = aws_security_group.app.id
}

output "data_security_group_id" {
  description = "Data security group ID"
  value       = aws_security_group.data.id
}
