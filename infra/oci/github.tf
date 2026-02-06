# ==============================================================================
# GitHub Provider & Repository Management
# ==============================================================================
# Purpose: Enforce branch protection rules and repository policies via IaC
# Owner: Platform Engineering Team
# Security: Requires github_token with 'repo' and 'admin:repo_hook' scopes
# ==============================================================================
# NOTE: Provider version is declared in main.tf (DRY principle)
# Secrets loaded from SOPS-encrypted file via data.sops_file.secrets
# ==============================================================================

provider "github" {
  token = local.secrets["github_token"]
  owner = var.github_owner
}

# ==============================================================================
# Repository Configuration
# ==============================================================================

resource "github_repository" "homelab" {
  name        = "homelab"
  description = "Production-grade hybrid cloud platform (Oracle Cloud + Raspberry Pi)"
  visibility  = "private"

  # Git Flow Configuration
  allow_merge_commit     = false
  allow_squash_merge     = true
  allow_rebase_merge     = false
  delete_branch_on_merge = true

  # Security Hardening
  vulnerability_alerts = true
  has_issues           = true
  has_wiki             = false
  has_downloads        = false

  # Backup & Recovery
  archived           = false
  archive_on_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

# ==============================================================================
# Local Variables
# ==============================================================================

locals {
  # Define branches that require protection (DRY principle)
  protected_branches = toset(["main", "develop"])
}

# ==============================================================================
# Branch Protection (DRY - Applies to all protected branches)
# ==============================================================================

resource "github_branch_protection" "default" {
  for_each = local.protected_branches

  repository_id = github_repository.homelab.node_id
  pattern       = each.key

  # Mandatory Status Checks
  required_status_checks {
    strict   = true
    contexts = ["Pipeline Gate"]
  }

  # Peer Review Requirement
  required_pull_request_reviews {
    required_approving_review_count = 1
    dismiss_stale_reviews           = true
    require_code_owner_reviews      = false
    require_last_push_approval      = true
  }

  # Security: GPG Signing Enforcement
  require_signed_commits = true

  # Zero-Tolerance Policy
  enforce_admins = true

  # Protection Against Force Push
  allows_force_pushes = false

  # Prevent branch deletion
  allows_deletions = false

  # Require linear history (squash merges only)
  required_linear_history = true

  # Require conversation resolution before merging
  require_conversation_resolution = true
}

# ==============================================================================
# Outputs
# ==============================================================================

output "repository_url" {
  description = "Full URL to the GitHub repository"
  value       = github_repository.homelab.html_url
}

output "branch_protection_status" {
  description = "Status of protected branches"
  value = {
    for branch, protection in github_branch_protection.default :
    branch => "Protected with ${protection.required_pull_request_reviews[0].required_approving_review_count} approval(s) + signed commits"
  }
}
