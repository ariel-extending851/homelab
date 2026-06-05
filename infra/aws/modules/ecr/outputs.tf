# ==============================================================================
# ECR Module Outputs
# ==============================================================================

output "repository_arns" {
  description = "ARNs of the ECR repositories — wired into the k3s_node IAM pull policy."
  value       = [for r in aws_ecr_repository.repos : r.arn]
}

output "repository_urls" {
  description = "Repository URLs keyed by name, for docker push / image refs in manifests."
  value       = { for name, r in aws_ecr_repository.repos : name => r.repository_url }
}
