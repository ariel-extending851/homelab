# ==============================================================================
# Compute Module Outputs
# ==============================================================================

output "k3s_server_public_ip" {
  description = "Public IP of k3s server node"
  value       = length(data.aws_instances.k3s_server.public_ips) > 0 ? data.aws_instances.k3s_server.public_ips[0] : ""
}

output "k3s_server_private_ip" {
  description = "Private IP of k3s server node"
  value       = length(data.aws_instances.k3s_server.private_ips) > 0 ? data.aws_instances.k3s_server.private_ips[0] : ""
}

output "k3s_agent_public_ip" {
  description = "Public IP of k3s agent node"
  value       = length(data.aws_instances.k3s_agent.public_ips) > 0 ? data.aws_instances.k3s_agent.public_ips[0] : ""
}

output "k3s_agent_private_ip" {
  description = "Private IP of k3s agent node"
  value       = length(data.aws_instances.k3s_agent.private_ips) > 0 ? data.aws_instances.k3s_agent.private_ips[0] : ""
}

output "k3s_server_instance_id" {
  description = "EC2 instance ID of k3s server"
  value       = length(data.aws_instances.k3s_server.ids) > 0 ? data.aws_instances.k3s_server.ids[0] : ""
}

output "k3s_agent_instance_id" {
  description = "EC2 instance ID of k3s agent"
  value       = length(data.aws_instances.k3s_agent.ids) > 0 ? data.aws_instances.k3s_agent.ids[0] : ""
}

output "ssh_key_name" {
  description = "Name of the SSH key pair (null in LocalStack test mode)"
  value       = var.localstack_test == "yes" ? null : aws_key_pair.homelab[0].key_name
}

output "iam_role_name" {
  description = "Name of the IAM role for k3s nodes"
  value       = aws_iam_role.k3s_node.name
}

output "iam_role_arn" {
  description = "ARN of the IAM role for k3s nodes"
  value       = aws_iam_role.k3s_node.arn
}
