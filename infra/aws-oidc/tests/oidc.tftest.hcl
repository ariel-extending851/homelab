# Tests for the GitHub Actions OIDC provider and IAM role configuration.

mock_provider "aws" {
  mock_resource "aws_iam_policy" {
    defaults = {
      arn = "arn:aws:iam::123456789012:policy/mock-policy"
    }
  }
}

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
    condition     = jsondecode(aws_iam_role.github_actions_terraform_plan.assume_role_policy).Statement[0].Condition.StringLike["token.actions.githubusercontent.com:sub"] == "repo:ariel-extending851/homelab:*"
    error_message = "Trust policy sub condition must be scoped to repo:ariel-extending851/homelab:*"
  }
}

# ── apply role: name + Environment-pinned trust policy ────────────────────────

run "apply_role_naming" {
  assert {
    condition     = aws_iam_role.github_actions_terraform_apply.name == "github-actions-terraform-apply"
    error_message = "Apply role must be named 'github-actions-terraform-apply'"
  }
  assert {
    condition     = aws_iam_role.github_actions_terraform_apply.tags["Project"] == "homelab"
    error_message = "Apply role must have Project=homelab tag"
  }
}

run "apply_role_trust_pinned_to_environments" {
  assert {
    condition = contains(
      jsondecode(aws_iam_role.github_actions_terraform_apply.assume_role_policy).Statement[0].Condition.StringLike["token.actions.githubusercontent.com:sub"],
      "repo:ariel-extending851/homelab:environment:production"
    )
    error_message = "Apply role trust must allow production Environment"
  }
  assert {
    condition = contains(
      jsondecode(aws_iam_role.github_actions_terraform_apply.assume_role_policy).Statement[0].Condition.StringLike["token.actions.githubusercontent.com:sub"],
      "repo:ariel-extending851/homelab:environment:staging-deploy"
    )
    error_message = "Apply role trust must allow staging-deploy Environment"
  }
  assert {
    condition = contains(
      jsondecode(aws_iam_role.github_actions_terraform_apply.assume_role_policy).Statement[0].Condition.StringLike["token.actions.githubusercontent.com:sub"],
      "repo:ariel-extending851/homelab:environment:production-approval"
    )
    error_message = "Apply role trust must allow production-approval Environment"
  }
}

run "apply_role_has_permissions_boundary" {
  assert {
    condition     = aws_iam_role.github_actions_terraform_apply.permissions_boundary == aws_iam_policy.terraform_apply_boundary.arn
    error_message = "Apply role must have a permissions boundary attached (public-repo defense-in-depth)"
  }
}

run "apply_role_boundary_denies_admin_attach" {
  assert {
    condition = anytrue([
      for stmt in jsondecode(aws_iam_policy.terraform_apply_boundary.policy).Statement :
      stmt.Effect == "Deny" && contains(flatten([try(stmt.Action, [])]), "iam:AttachRolePolicy")
    ])
    error_message = "Permissions boundary must deny attaching iam:AttachRolePolicy with admin/poweruser/iamfull policies"
  }
}

# ── homelab principal boundary (cap on roles created by apply role) ───────────
#
# IAM policy JSON serializes single-element Action arrays as bare strings
# ({"Action": "*"} not {"Action": ["*"]}). The boundary's allow-everything-
# then-deny statement uses Action = "*", which becomes a string scalar after
# jsondecode. Wrap with flatten([...]) so contains() sees a list either way:
#   flatten([list])   → list (unchanged)
#   flatten([string]) → [string]
# Without the wrap, terraform 1.11 fails with "argument must be list,
# tuple, or set" when the for-loop hits the scalar Action statement.

run "principal_boundary_exists_and_denies_iam" {
  assert {
    condition     = aws_iam_policy.homelab_principal_boundary.name == "homelab-principal-boundary"
    error_message = "homelab_principal_boundary must exist with the canonical name"
  }
  assert {
    condition = anytrue([
      for stmt in jsondecode(aws_iam_policy.homelab_principal_boundary.policy).Statement :
      stmt.Effect == "Deny" && contains(flatten([try(stmt.Action, [])]), "iam:*")
    ])
    error_message = "homelab_principal_boundary must explicitly Deny iam:* — closes the privilege-escalation chain"
  }
}

run "principal_boundary_denies_assume_role" {
  assert {
    condition = anytrue([
      for stmt in jsondecode(aws_iam_policy.homelab_principal_boundary.policy).Statement :
      stmt.Effect == "Deny" && contains(flatten([try(stmt.Action, [])]), "sts:AssumeRole")
    ])
    error_message = "homelab_principal_boundary must Deny sts:AssumeRole — blocks cross-account pivot from a hijacked child role"
  }
}

# ── apply role enforces the boundary on every Create ──────────────────────────

run "apply_create_role_requires_principal_boundary" {
  assert {
    condition = anytrue([
      for stmt in jsondecode(aws_iam_role_policy.terraform_apply_permissions.policy).Statement :
      contains(flatten([try(stmt.Action, [])]), "iam:CreateRole") &&
      try(stmt.Condition.StringEquals["iam:PermissionsBoundary"], null) == aws_iam_policy.homelab_principal_boundary.arn
    ])
    error_message = "Inline policy: iam:CreateRole must be Conditioned on iam:PermissionsBoundary = homelab_principal_boundary.arn"
  }
}

run "apply_create_user_requires_principal_boundary" {
  assert {
    condition = anytrue([
      for stmt in jsondecode(aws_iam_role_policy.terraform_apply_permissions.policy).Statement :
      contains(flatten([try(stmt.Action, [])]), "iam:CreateUser") &&
      try(stmt.Condition.StringEquals["iam:PermissionsBoundary"], null) == aws_iam_policy.homelab_principal_boundary.arn
    ])
    error_message = "Inline policy: iam:CreateUser must be Conditioned on iam:PermissionsBoundary = homelab_principal_boundary.arn"
  }
}

run "apply_inline_denies_boundary_removal" {
  assert {
    condition = anytrue([
      for stmt in jsondecode(aws_iam_role_policy.terraform_apply_permissions.policy).Statement :
      stmt.Effect == "Deny" && contains(flatten([try(stmt.Action, [])]), "iam:DeleteRolePermissionsBoundary")
    ])
    error_message = "Inline policy must Deny iam:DeleteRolePermissionsBoundary so the boundary cannot be detached"
  }
}

run "apply_boundary_denies_boundary_removal" {
  assert {
    condition = anytrue([
      for stmt in jsondecode(aws_iam_policy.terraform_apply_boundary.policy).Statement :
      stmt.Effect == "Deny" && contains(flatten([try(stmt.Action, [])]), "iam:DeleteRolePermissionsBoundary")
    ])
    error_message = "Apply role boundary must Deny iam:DeleteRolePermissionsBoundary too — defense in depth"
  }
}
