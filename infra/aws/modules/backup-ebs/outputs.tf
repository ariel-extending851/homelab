# ==============================================================================
# EBS Snapshot Lifecycle Module Outputs
# ==============================================================================

output "dlm_policy_id" {
  description = "ID of the DLM lifecycle policy."
  value       = aws_dlm_lifecycle_policy.ebs.id
}

output "dlm_role_arn" {
  description = "ARN of the DLM service role."
  value       = aws_iam_role.dlm.arn
}
