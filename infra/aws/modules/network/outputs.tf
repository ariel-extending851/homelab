# ==============================================================================
# Network Module Outputs
# ==============================================================================

output "vpc_id" {
  description = "ID of the default VPC"
  value       = data.aws_vpc.default.id
}

output "vpc_cidr" {
  description = "CIDR block of the default VPC"
  value       = data.aws_vpc.default.cidr_block
}

output "subnet_ids" {
  description = "List of default subnet IDs"
  value       = data.aws_subnets.default.ids
}

output "security_group_id" {
  description = "ID of the k3s cluster security group"
  value       = aws_security_group.k3s_cluster.id
}

output "security_group_name" {
  description = "Name of the k3s cluster security group"
  value       = aws_security_group.k3s_cluster.name
}
