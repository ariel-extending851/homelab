# GitHub Provider Setup Instructions

## Prerequisites

### 1. Generate GitHub Personal Access Token (PAT)

1. Navigate to: https://github.com/settings/tokens/new
2. Token Configuration:
   - **Name:** `Terraform Homelab IaC`
   - **Expiration:** 90 days (recommended for security)
   - **Scopes:** Select the following:
     - ✅ `repo` (Full control of private repositories)
     - ✅ `admin:repo_hook` (Full control of repository hooks)

3. Click **Generate token**
4. **CRITICAL:** Copy the token immediately (it won't be shown again)

### 2. Store Token Securely

**Option A: Environment Variable (Recommended for CI/CD)**
```bash
export TF_VAR_github_token="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

**Option B: Terraform Variables File (Local Development)**
```bash
# Add to infra/oci/terraform.tfvars (NEVER commit this file)
github_token = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

**Option C: Use `pass` (Password Manager)**
```bash
# Store token
pass insert terraform/github_token

# Use in Terraform
export TF_VAR_github_token=$(pass show terraform/github_token)
```

## Terraform Execution

### Step 1: Initialize Provider
```bash
cd infra/oci
terraform init
```

**Expected Output:**
```
Initializing provider plugins...
- Finding integrations/github versions matching "~> 6.0"...
- Installing integrations/github v6.x.x...

Terraform has been successfully initialized!
```

### Step 2: Preview Changes
```bash
terraform plan
```

**Expected Output:**
```
Terraform will perform the following actions:

  # github_branch_protection.develop will be created
  + resource "github_branch_protection" "develop" {
      + allows_deletions              = false
      + allows_force_pushes           = false
      + enforce_admins                = true
      + pattern                       = "develop"
      + require_signed_commits        = true
      + required_linear_history       = true
      + repository_id                 = (known after apply)
      ...
    }

  # github_branch_protection.main will be created
  + resource "github_branch_protection" "main" {
      + allows_deletions              = false
      + allows_force_pushes           = false
      + enforce_admins                = true
      + pattern                       = "main"
      + require_signed_commits        = true
      + required_linear_history       = true
      + repository_id                 = (known after apply)
      ...
    }

  # github_repository.homelab will be created
  + resource "github_repository" "homelab" {
      + allow_merge_commit     = false
      + allow_rebase_merge     = false
      + allow_squash_merge     = true
      + delete_branch_on_merge = true
      + name                   = "homelab"
      + visibility             = "public"
      ...
    }

Plan: 3 to add, 0 to change, 0 to destroy.
```

### Step 3: Apply Configuration
```bash
terraform apply
```

**Review the plan carefully, then type:** `yes`

### Step 4: Verify Deployment

**Option A: GitHub Web UI**
1. Navigate to: https://github.com/ariel99gf/homelab/settings/branches
2. Verify that `main` and `develop` branches show:
   - ✅ Require status checks to pass before merging
   - ✅ Require branches to be up to date before merging
   - ✅ Status checks that are required: `CI Validation`
   - ✅ Require a pull request before merging (1 approval)
   - ✅ Require signed commits
   - ✅ Include administrators

**Option B: GitHub CLI**
```bash
gh api repos/ariel99gf/homelab/branches/main/protection | jq '{
  required_status_checks,
  required_pull_request_reviews,
  required_signatures,
  enforce_admins
}'
```

**Expected Output:**
```json
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["CI Validation"]
  },
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true
  },
  "required_signatures": {
    "enabled": true
  },
  "enforce_admins": {
    "enabled": true
  }
}
```

## Security Considerations

### 🔒 Token Management Best Practices

1. **Rotation Policy:**
   - Rotate PAT every 90 days
   - Update `TF_VAR_github_token` after rotation

2. **Access Control:**
   - Never commit `terraform.tfvars` to version control
   - Add to `.gitignore`:
     ```
     # Terraform sensitive files
     *.tfvars
     *.tfvars.json
     ```

3. **Principle of Least Privilege:**
   - Use a dedicated service account for Terraform (not your personal account)
   - Revoke token immediately if compromised

4. **Audit Trail:**
   - Check GitHub Security Log regularly: https://github.com/settings/security-log
   - Monitor for unauthorized changes to branch protection

## Troubleshooting

### Error: "Resource already exists"
If the repository already exists with different settings:

```bash
# Import existing repository
terraform import github_repository.homelab homelab

# Import existing branch protections (note the for_each syntax)
terraform import 'github_branch_protection.default["main"]' homelab:main
terraform import 'github_branch_protection.default["develop"]' homelab:develop
```

### Error: "Insufficient permissions"
Verify PAT scopes:
```bash
# Check token scopes
curl -H "Authorization: token $TF_VAR_github_token" \
     -I https://api.github.com/user | grep -i "x-oauth-scopes"
```

Expected: `x-oauth-scopes: admin:repo_hook, repo`

### Error: "Context 'CI Validation' not found"
The status check context must match your GitHub Actions workflow:

```yaml
# .github/workflows/ci.yml
name: CI Validation  # ← Must match exactly
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # ... your CI steps
```

## Post-Deployment Checklist

- [ ] GitHub PAT stored securely (not in VCS)
- [ ] Branch protection rules applied to `main` and `develop`
- [ ] Repository settings configured (squash merge only)
- [ ] CI workflow name matches required status check context
- [ ] Test protection by attempting a force push (should fail)
- [ ] Document PAT rotation date in team calendar

## Git Notes Command (Post-Commit)

After committing these changes, attach metadata:

```bash
git notes add -m "Task: GitHub IaC Implementation | Changes: Added Terraform GitHub provider with branch protection for main/develop branches, enforcing signed commits and PR reviews" $(git rev-parse HEAD)
```

## AWS DOP-C02 Exam Tip

**AWS Equivalent:** In AWS, this GitHub branch protection pattern maps to:
- **AWS CodeCommit:** Uses approval rule templates with `minimumNumberOfApprovals` and IAM policies to enforce MFA/signing
- **AWS CodePipeline:** Can gate deployments with manual approval stages
- **AWS Config Rules:** `required-tags`, `approved-amis-by-id` enforce compliance policies
- **Key Difference:** GitHub's `enforce_admins` has no direct CodeCommit equivalent; AWS uses IAM boundary policies instead

**Exam Scenario:** "A company wants to prevent direct commits to production branches..." → Solution: Enable approval rules + restrict push permissions to service accounts only.
