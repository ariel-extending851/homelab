output "role_arn" {
  description = "ARN of the GitHub Actions OIDC role — add as vars.AWS_ACCOUNT_ID is not needed; use this ARN directly in the workflow."
  value       = aws_iam_role.github_actions_terraform_plan.arn
}

output "oidc_provider_arn" {
  description = "ARN of the GitHub Actions OIDC provider."
  value       = aws_iam_openid_connect_provider.github_actions.arn
}
