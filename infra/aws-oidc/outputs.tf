output "plan_role_arn" {
  description = "ARN of the read-only terraform plan role used by ci-validation.yml."
  value       = aws_iam_role.github_actions_terraform_plan.arn
}

output "apply_role_arn" {
  description = "ARN of the terraform apply role used by ci-deployment.yml + rollback.yml. Trust pinned to staging-deploy/production/production-approval Environments."
  value       = aws_iam_role.github_actions_terraform_apply.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider."
  value       = aws_iam_openid_connect_provider.github_actions.arn
}

output "aws_account_id" {
  description = "AWS account ID — set as the GitHub repo variable AWS_ACCOUNT_ID after first apply."
  value       = data.aws_caller_identity.current.account_id
}
