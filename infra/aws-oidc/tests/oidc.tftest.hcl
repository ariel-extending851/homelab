# Tests for the GitHub Actions OIDC provider and IAM role configuration.

mock_provider "aws" {}

# ── OIDC provider URL ─────────────────────────────────────────────────────────

run "oidc_provider_points_to_github_actions" {
  assert {
    condition     = aws_iam_openid_connect_provider.github_actions.url == "https://token.actions.githubusercontent.com"
    error_message = "OIDC provider must use the GitHub Actions token endpoint"
  }
  assert {
    condition     = contains(aws_iam_openid_connect_provider.github_actions.client_id_list, "sts.amazonaws.com")
    error_message = "OIDC client ID must be 'sts.amazonaws.com' for AWS federation"
  }
}

# ── IAM role naming ───────────────────────────────────────────────────────────

run "iam_role_naming_convention" {
  assert {
    condition     = aws_iam_role.github_actions_terraform_plan.name == "github-actions-terraform-plan"
    error_message = "OIDC IAM role must be named 'github-actions-terraform-plan'"
  }
  assert {
    condition     = aws_iam_role.github_actions_terraform_plan.tags["Project"] == "homelab"
    error_message = "IAM role must have Project=homelab tag"
  }
}

# ── repo scope in trust policy ────────────────────────────────────────────────

run "trust_policy_scoped_to_repo" {
  assert {
    condition = jsondecode(aws_iam_role.github_actions_terraform_plan.assume_role_policy).Statement[0].Condition.StringLike["token.actions.githubusercontent.com:sub"] == "repo:ariel99gf/homelab:*"
    error_message = "Trust policy sub condition must be scoped to repo:ariel99gf/homelab:*"
  }
}
