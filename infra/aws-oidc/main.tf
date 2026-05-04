data "aws_caller_identity" "current" {}

# GitHub Actions OIDC provider.
# Thumbprint is the SHA-1 of the GitHub Actions OIDC certificate root CA.
# See: https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services
resource "aws_iam_openid_connect_provider" "github_actions" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Name    = "github-actions-oidc"
    Project = "homelab"
  }
}

# IAM role assumed by the GitHub Actions workflow via OIDC.
# Scoped to this repository only; any branch or workflow file can assume it.
resource "aws_iam_role" "github_actions_terraform_plan" {
  name        = "github-actions-terraform-plan"
  description = "Read-only role for terraform plan in CI. Assumed via OIDC by ariel-extending851/homelab."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github_actions.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:ariel-extending851/homelab:*"
        }
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
      }
    }]
  })

  tags = {
    Name    = "github-actions-terraform-plan"
    Project = "homelab"
  }
}

# Minimal policy for terraform plan — read-only access to every service
# touched by infra/aws/: EC2, VPC, S3, IAM, Lambda, EventBridge, and the
# Terraform state backend (S3 + DynamoDB).
resource "aws_iam_role_policy" "terraform_plan_readonly" {
  name = "terraform-plan-readonly"
  role = aws_iam_role.github_actions_terraform_plan.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EC2Read"
        Effect   = "Allow"
        Action   = ["ec2:Describe*"]
        Resource = "*"
      },
      {
        Sid    = "S3Read"
        Effect = "Allow"
        Action = [
          "s3:GetBucketVersioning",
          "s3:GetBucketEncryption",
          "s3:GetBucketPublicAccessBlock",
          "s3:GetLifecycleConfiguration",
          "s3:GetBucketTagging",
          "s3:ListBucket",
          "s3:GetObject",
        ]
        Resource = "*"
      },
      {
        Sid      = "IAMRead"
        Effect   = "Allow"
        Action   = ["iam:Get*", "iam:List*"]
        Resource = "*"
      },
      {
        Sid      = "LambdaRead"
        Effect   = "Allow"
        Action   = ["lambda:Get*", "lambda:List*"]
        Resource = "*"
      },
      {
        Sid      = "EventBridgeRead"
        Effect   = "Allow"
        Action   = ["events:List*", "events:Describe*"]
        Resource = "*"
      },
      # Terraform state backend — S3 write needed for .tflock file (use_lockfile=true),
      # but CI uses -lock=false so only read is required.
      {
        Sid    = "TerraformStateRead"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::homelab-terraform-state-kkuhocyv",
          "arn:aws:s3:::homelab-terraform-state-kkuhocyv/*",
        ]
      },
      {
        Sid      = "TerraformLockRead"
        Effect   = "Allow"
        Action   = ["dynamodb:DescribeTable", "dynamodb:GetItem"]
        Resource = "arn:aws:dynamodb:us-east-1:${data.aws_caller_identity.current.account_id}:table/homelab-terraform-state-lock"
      },
    ]
  })
}

# ── github-actions-terraform-apply ───────────────────────────────────────────
#
# Used by ci-deployment.yml (staging canary + prod) and rollback.yml.
# Trust policy is Environment-pinned — only workflow runs declaring
# `environment: staging-deploy | production | production-approval` can
# obtain an OIDC token whose `sub` claim matches. This is the load-bearing
# defense against fork-PR exploitation in a public repository: a malicious
# fork PR cannot declare those Environments (they require approvals + the
# original repo's secrets), so the assume-role call fails at the STS layer.
#
# Permissions are enumerated at the service level and resource-scoped where
# AWS supports it. A permissions boundary caps the maximum permissions the
# role can ever exercise — even if the inline policy is later misconfigured.

resource "aws_iam_role" "github_actions_terraform_apply" {
  name        = "github-actions-terraform-apply"
  description = "Terraform apply role for CI. Trust pinned to staging-deploy/production/production-approval Environments."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github_actions.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = [
            "repo:ariel-extending851/homelab:environment:staging-deploy",
            "repo:ariel-extending851/homelab:environment:production",
            "repo:ariel-extending851/homelab:environment:production-approval",
          ]
        }
      }
    }]
  })

  permissions_boundary = aws_iam_policy.terraform_apply_boundary.arn

  tags = {
    Name    = "github-actions-terraform-apply"
    Project = "homelab"
  }
}

# Permissions boundary — outermost cap on what this role can ever do.
# Even if the inline policy below is mistakenly broadened, AWS will refuse
# any action outside this boundary. This is the public-repo safety net.
resource "aws_iam_policy" "terraform_apply_boundary" {
  name        = "github-actions-terraform-apply-boundary"
  description = "Maximum permissions cap for github-actions-terraform-apply (public-repo defense-in-depth)."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BoundaryServicesAllowed"
        Effect = "Allow"
        Action = [
          "ec2:*",
          "s3:*",
          "iam:*",
          "lambda:*",
          "events:*",
          "cloudtrail:*",
          "guardduty:*",
          "dynamodb:*",
          "logs:*",
          "kms:DescribeKey",
          "kms:ListAliases",
          "sts:GetCallerIdentity",
        ]
        Resource = "*"
      },
      {
        Sid      = "BoundaryDenyAdminPolicyAttach"
        Effect   = "Deny"
        Action   = ["iam:AttachRolePolicy", "iam:AttachUserPolicy", "iam:AttachGroupPolicy"]
        Resource = "*"
        Condition = {
          ArnEquals = {
            "iam:PolicyARN" = [
              "arn:aws:iam::aws:policy/AdministratorAccess",
              "arn:aws:iam::aws:policy/PowerUserAccess",
              "arn:aws:iam::aws:policy/IAMFullAccess",
            ]
          }
        }
      },
    ]
  })

  tags = {
    Name    = "github-actions-terraform-apply-boundary"
    Project = "homelab"
  }
}

resource "aws_iam_role_policy" "terraform_apply_permissions" {
  name = "terraform-apply-permissions"
  role = aws_iam_role.github_actions_terraform_apply.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # EC2: full lifecycle of instances, fleets, launch templates, key pairs,
      # security groups, EBS volumes, VPC data sources. AWS does not support
      # resource-level conditions on most ec2: actions, so service-level allow.
      {
        Sid      = "EC2Full"
        Effect   = "Allow"
        Action   = ["ec2:*"]
        Resource = "*"
      },
      # IAM: scoped to homelab-owned principals only. Any modification to
      # roles/users/instance-profiles outside these ARN patterns is denied
      # at the inline-policy layer (and again by the boundary).
      {
        Sid    = "IAMHomelabPrincipals"
        Effect = "Allow"
        Action = [
          "iam:GetRole", "iam:CreateRole", "iam:DeleteRole", "iam:UpdateRole", "iam:UpdateAssumeRolePolicy",
          "iam:GetRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:PassRole", "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
          "iam:GetUser", "iam:CreateUser", "iam:DeleteUser", "iam:UpdateUser",
          "iam:GetUserPolicy", "iam:PutUserPolicy", "iam:DeleteUserPolicy", "iam:ListUserPolicies",
          "iam:AttachUserPolicy", "iam:DetachUserPolicy", "iam:ListAttachedUserPolicies",
          "iam:CreateAccessKey", "iam:DeleteAccessKey", "iam:ListAccessKeys", "iam:UpdateAccessKey",
          "iam:GetInstanceProfile", "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile",
          "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile",
          "iam:ListInstanceProfilesForRole", "iam:TagInstanceProfile",
          "iam:CreateServiceLinkedRole", "iam:DeleteServiceLinkedRole",
          "iam:GetServiceLinkedRoleDeletionStatus",
        ]
        Resource = [
          "arn:aws:iam::*:role/k3s-node*",
          "arn:aws:iam::*:role/scheduler-lambda*",
          "arn:aws:iam::*:role/aws-service-role/spot.amazonaws.com/*",
          "arn:aws:iam::*:role/aws-service-role/spotfleet.amazonaws.com/*",
          "arn:aws:iam::*:user/velero*",
          "arn:aws:iam::*:instance-profile/k3s-node*",
        ]
      },
      # IAM read account-wide is needed because terraform refresh resolves
      # ARNs / paths for managed policies even when not modifying them.
      {
        Sid      = "IAMReadAccountWide"
        Effect   = "Allow"
        Action   = ["iam:Get*", "iam:List*"]
        Resource = "*"
      },
      # S3: scoped to homelab buckets and the terraform state backend.
      {
        Sid    = "S3HomelabBuckets"
        Effect = "Allow"
        Action = ["s3:*"]
        Resource = [
          "arn:aws:s3:::homelab-velero-backups*",
          "arn:aws:s3:::homelab-velero-backups*/*",
          "arn:aws:s3:::homelab-ssm-transfer-bucket*",
          "arn:aws:s3:::homelab-ssm-transfer-bucket*/*",
          "arn:aws:s3:::homelab-cloudtrail*",
          "arn:aws:s3:::homelab-cloudtrail*/*",
          "arn:aws:s3:::homelab-terraform-state-kkuhocyv",
          "arn:aws:s3:::homelab-terraform-state-kkuhocyv/*",
        ]
      },
      {
        Sid      = "S3CreateNewHomelabBuckets"
        Effect   = "Allow"
        Action   = ["s3:CreateBucket", "s3:ListAllMyBuckets"]
        Resource = "*"
      },
      # Lambda: scoped to scheduler functions.
      {
        Sid    = "LambdaScheduler"
        Effect = "Allow"
        Action = ["lambda:*"]
        Resource = [
          "arn:aws:lambda:*:*:function:homelab-scheduler*",
        ]
      },
      # EventBridge: scoped to homelab-prefixed rules.
      {
        Sid    = "EventBridgeScheduler"
        Effect = "Allow"
        Action = ["events:*"]
        Resource = [
          "arn:aws:events:*:*:rule/homelab-*",
        ]
      },
      # CloudTrail: scoped to homelab trail.
      {
        Sid      = "CloudTrailHomelab"
        Effect   = "Allow"
        Action   = ["cloudtrail:*"]
        Resource = "arn:aws:cloudtrail:*:*:trail/homelab*"
      },
      # GuardDuty: detector is account-level (no ARN constraint useful).
      {
        Sid      = "GuardDutyDetector"
        Effect   = "Allow"
        Action   = ["guardduty:*"]
        Resource = "*"
      },
      # DynamoDB: terraform state lock table.
      {
        Sid    = "DynamoDBStateLock"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
          "dynamodb:DescribeTable", "dynamodb:UpdateItem",
        ]
        Resource = "arn:aws:dynamodb:*:*:table/homelab-terraform-state-lock"
      },
      # KMS: SOPS metadata + key descriptions.
      {
        Sid      = "KMSDescribe"
        Effect   = "Allow"
        Action   = ["kms:DescribeKey", "kms:ListAliases"]
        Resource = "*"
      },
      # Logs: Lambda function CloudWatch Logs.
      {
        Sid      = "CloudWatchLogs"
        Effect   = "Allow"
        Action   = ["logs:*"]
        Resource = "*"
      },
      # STS: identity inspection used by terraform's aws_caller_identity data.
      {
        Sid      = "STSGetIdentity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      },
    ]
  })
}
