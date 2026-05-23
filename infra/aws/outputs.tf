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
  value       = var.enable_scheduling ? "~$24.59/month (t3.medium + t3.small, 45% uptime with scheduling + EBS storage)" : "~$45.55/month (t3.medium + t3.small, 24/7 + EBS storage)"
}

# Scheduler Outputs (only when enabled)
output "scheduler_function_url" {
  description = "Lambda function URL for manual instance control"
  value       = var.enable_scheduling && var.localstack_test == "no" ? module.scheduler[0].lambda_function_url : "Scheduling disabled"
}

output "manual_start_command" {
  description = "Command to manually start instances"
  value       = var.enable_scheduling && var.localstack_test == "no" ? module.scheduler[0].manual_start_command : "Scheduling disabled"
}

output "manual_stop_command" {
  description = "Command to manually stop instances"
  value       = var.enable_scheduling && var.localstack_test == "no" ? module.scheduler[0].manual_stop_command : "Scheduling disabled"
}

output "schedule_summary" {
  description = "Instance scheduling summary"
  value       = var.enable_scheduling && var.localstack_test == "no" ? module.scheduler[0].schedule_summary : "Scheduling disabled - instances run 24/7"
}

# Velero outputs (bucket name + IAM access keys) moved to infra/aws-velero/
# so the always-on backup slice can be applied and destroyed independently
# of this hybrid stack. Read them from there:
#   cd infra/aws-velero && terraform output -raw velero_backup_bucket_name
#   cd infra/aws-velero && terraform output -raw velero_aws_access_key_id
#   cd infra/aws-velero && terraform output -raw velero_aws_secret_access_key

# Observability Outputs (Alloy cold-storage S3 bucket)
output "observability_bucket_id" {
  description = "Name of the cold-storage S3 bucket consumed by the Alloy DaemonSet (otelcol.exporter.awss3). Empty under LocalStack."
  value       = var.localstack_test == "no" ? module.observability[0].bucket_id : ""
}

output "observability_bucket_arn" {
  description = "ARN of the cold-storage S3 bucket — wired into the k3s_node IAM role policy. Empty under LocalStack."
  value       = var.localstack_test == "no" ? module.observability[0].bucket_arn : ""
}

# Audit Outputs (CloudTrail + GuardDuty)
output "audit_trail_name" {
  description = "Name of the CloudTrail audit trail (empty under LocalStack)."
  value       = var.localstack_test == "no" ? module.audit[0].trail_name : ""
}

output "audit_trail_bucket_name" {
  description = "S3 bucket holding CloudTrail logs (empty under LocalStack)."
  value       = var.localstack_test == "no" ? module.audit[0].trail_bucket_name : ""
}

output "guardduty_detector_id" {
  description = "ID of the GuardDuty detector (empty under LocalStack)."
  value       = var.localstack_test == "no" ? module.audit[0].guardduty_detector_id : ""
}
