# ==============================================================================
# Root Module Outputs
# ==============================================================================

# Network Outputs
output "vpc_id" {
  description = "ID of the default VPC"
  value       = module.network.vpc_id
}

output "security_group_id" {
  description = "Security group ID for k3s cluster"
  value       = module.network.security_group_id
}

# Compute Outputs
output "k3s_server_public_ip" {
  description = "Public IP of k3s server node"
  value       = module.k3s_cluster.k3s_server_public_ip
}

output "k3s_server_private_ip" {
  description = "Private IP of k3s server node"
  value       = module.k3s_cluster.k3s_server_private_ip
}

output "k3s_agent_public_ip" {
  description = "Public IP of k3s agent node"
  value       = module.k3s_cluster.k3s_agent_public_ip
}

output "k3s_agent_private_ip" {
  description = "Private IP of k3s agent node"
  value       = module.k3s_cluster.k3s_agent_private_ip
}

output "k3s_server_instance_id" {
  description = "EC2 instance ID of k3s server"
  value       = module.k3s_cluster.k3s_server_instance_id
}

output "k3s_agent_instance_id" {
  description = "EC2 instance ID of k3s agent"
  value       = module.k3s_cluster.k3s_agent_instance_id
}

# Helper Outputs
output "ssh_command_server" {
  description = "SSH command to connect to k3s server"
  value       = "ssh -i ~/.ssh/${var.ssh_key_name} ec2-user@${module.k3s_cluster.k3s_server_public_ip}"
}

output "ssh_command_agent" {
  description = "SSH command to connect to k3s agent"
  value       = "ssh -i ~/.ssh/${var.ssh_key_name} ec2-user@${module.k3s_cluster.k3s_agent_public_ip}"
}

output "kubeconfig_command" {
  description = "Command to retrieve kubeconfig from server"
  value       = "scp -i ~/.ssh/${var.ssh_key_name} ec2-user@${module.k3s_cluster.k3s_server_public_ip}:/etc/rancher/k3s/k3s.yaml ~/.kube/config-homelab"
}

output "k3s_api_endpoint" {
  description = "k3s API endpoint (update in kubeconfig)"
  value       = "https://${module.k3s_cluster.k3s_server_public_ip}:6443"
}

output "estimated_monthly_cost_usd" {
  description = "Estimated monthly cost in USD (based on AWS Pricing Calculator)"
  value       = "~$17.65 (2× t3.small spot instances + 40GB gp3 EBS)"
}
