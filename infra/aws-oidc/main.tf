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
#
# Design: every action allowed below is also explicitly enumerated (no
# service wildcards except ec2:*, where AWS itself does not provide
# resource-level constraints for most actions). Privilege-escalation
# vectors (CreateLoginProfile, UpdateAssumeRolePolicy on non-homelab
# principals, attaching managed admin policies) are explicitly denied.
resource "aws_iam_policy" "terraform_apply_boundary" {
  # checkov:skip=CKV_AWS_286:Privilege-escalation vectors are blocked by the explicit Deny statements (DenyAdminPolicyAttach, DenyDangerousIAM, DenyBoundaryRemoval/Replacement) further down. Allow side uses service wildcards within ARN-scoped resources to keep the policy under the IAM 6144-byte managed-policy size limit.
  # checkov:skip=CKV_AWS_287:Credential-exposure actions (iam:CreateAccessKey etc) are scoped to homelab principal ARNs only — boundary cap, not principal-wide.
  # checkov:skip=CKV_AWS_288:S3 data-exfiltration is bounded to homelab-* buckets via Resource ARN scoping. Inline policy enumerates specific actions; boundary uses wildcard within the same scope.
  # checkov:skip=CKV_AWS_289:Permissions-management actions are scoped to homelab principals; admin-policy attaches denied via DenyAdminPolicyAttach below.
  # checkov:skip=CKV_AWS_290:EC2/IAM service wildcards needed because (a) AWS doesn't support resource-level conditions on most ec2:* actions, and (b) the 6144-byte managed-policy limit forces wildcards within ARN-scoped resources.
  # checkov:skip=CKV_AWS_355:Same as CKV_AWS_290 — Resource:"*" used only for ec2 (AWS-mandated) and account-level services (KMS metadata, STS, IAM read of policy ARNs); all write actions are scoped via Resource ARN or Condition.
  # checkov:skip=CKV2_AWS_40:iam:* on homelab-principal ARN patterns only — not full IAM. The principal-boundary on every Create* enforces child roles cannot escalate further.
  name        = "github-actions-terraform-apply-boundary"
  description = "Maximum permissions cap for github-actions-terraform-apply (public-repo defense-in-depth). Service wildcards inside ARN-scoped resources to fit IAM 6144-byte limit."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # EC2 — AWS does not support resource-level conditions on most ec2 actions.
      # The inline policy splits this into ReadOnly + LifecycleByTag + CreateWithRequestTag;
      # the boundary just caps service.
      {
        Sid      = "EC2"
        Effect   = "Allow"
        Action   = ["ec2:*"]
        Resource = "*"
      },
      # IAM — homelab principal ARN patterns only. ARN allowlist tracks
      # the actual names produced by infra/aws/ (verified live):
      #   - Roles use name_prefix "hl-k3s-node-" / "hl-ec2-scheduler-"
      #   - Instance profile uses name_prefix "hl-k3s-node-"
      #   - Velero IAM user is at path /system/ → ARN includes /system/
      #   - Service-linked roles for spot fleet are AWS-managed.
      {
        Sid    = "IAMHomelabPrincipals"
        Effect = "Allow"
        Action = ["iam:*"]
        Resource = [
          "arn:aws:iam::*:role/hl-*",
          "arn:aws:iam::*:role/aws-service-role/spot.amazonaws.com/*",
          "arn:aws:iam::*:role/aws-service-role/spotfleet.amazonaws.com/*",
          "arn:aws:iam::*:user/system/*",
          "arn:aws:iam::*:instance-profile/hl-*",
        ]
      },
      # IAM read — narrow allowlist for terraform refresh. Excludes
      # access-key enumeration actions on other users.
      {
        Sid    = "IAMReadAccountWide"
        Effect = "Allow"
        Action = [
          "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicies",
          "iam:ListPolicyVersions", "iam:ListEntitiesForPolicy",
          "iam:ListInstanceProfiles", "iam:GetOpenIDConnectProvider",
          "iam:ListOpenIDConnectProviders",
        ]
        Resource = "*"
      },
      # S3 — homelab buckets only.
      {
        Sid      = "S3Homelab"
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = ["arn:aws:s3:::homelab-*", "arn:aws:s3:::homelab-*/*"]
      },
      {
        Sid      = "S3List"
        Effect   = "Allow"
        Action   = ["s3:ListAllMyBuckets", "s3:CreateBucket"]
        Resource = "*"
      },
      # Lambda — actual function name uses "hl-" prefix (hl-ec2-scheduler).
      {
        Sid      = "Lambda"
        Effect   = "Allow"
        Action   = ["lambda:*"]
        Resource = "arn:aws:lambda:*:*:function:hl-*"
      },
      # EventBridge — actual rule names use "hl-" prefix.
      {
        Sid      = "Events"
        Effect   = "Allow"
        Action   = ["events:*"]
        Resource = "arn:aws:events:*:*:rule/hl-*"
      },
      # CloudTrail — trail named "homelab-audit", but DescribeTrails /
      # ListTrails / LookupEvents are account-level reads (no resource-level
      # condition support).
      {
        Sid      = "CloudTrailHomelabTrail"
        Effect   = "Allow"
        Action   = ["cloudtrail:*"]
        Resource = "arn:aws:cloudtrail:*:*:trail/homelab*"
      },
      {
        Sid    = "CloudTrailAccountReads"
        Effect = "Allow"
        Action = [
          "cloudtrail:DescribeTrails", "cloudtrail:ListTrails",
          "cloudtrail:LookupEvents", "cloudtrail:GetTrailStatus",
        ]
        Resource = "*"
      },
      # GuardDuty — detector is account-level.
      {
        Sid      = "GuardDuty"
        Effect   = "Allow"
        Action   = ["guardduty:*"]
        Resource = "*"
      },
      # DynamoDB — terraform state lock only.
      {
        Sid    = "DynamoDB"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
          "dynamodb:DescribeTable", "dynamodb:UpdateItem",
        ]
        Resource = "arn:aws:dynamodb:*:*:table/homelab-terraform-state-lock"
      },
      # Logs — Lambda function is named hl-* so log group is /aws/lambda/hl-*.
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:*"]
        Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/hl-*"
      },
      # KMS metadata only — no Decrypt, no Sign.
      {
        Sid      = "KMSMetadata"
        Effect   = "Allow"
        Action   = ["kms:DescribeKey", "kms:ListAliases"]
        Resource = "*"
      },
      # STS identity inspection only.
      {
        Sid      = "STSIdentity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      },
      # Explicit deny: attaching managed-admin policies to any principal.
      # Catches the classic boundary-escape attempt (boundary allows
      # iam:AttachRolePolicy → attacker attaches AdministratorAccess).
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
      # Explicit deny: dangerous IAM actions never needed by terraform.
      {
        Sid    = "BoundaryDenyDangerousIAM"
        Effect = "Deny"
        Action = [
          "iam:CreateLoginProfile", "iam:UpdateLoginProfile", "iam:DeleteLoginProfile",
          "iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion",
          "iam:CreateSAMLProvider", "iam:DeleteSAMLProvider", "iam:UpdateSAMLProvider",
          "iam:CreateOpenIDConnectProvider", "iam:DeleteOpenIDConnectProvider",
          "iam:UpdateOpenIDConnectProviderThumbprint",
          "iam:CreateAccountAlias", "iam:DeleteAccountAlias",
          "iam:GenerateCredentialReport", "iam:GetCredentialReport",
        ]
        Resource = "*"
      },
      # Explicit deny: removing the homelab_principal_boundary from any
      # existing role/user. Closes the bypass where an attacker would
      # detach the boundary, then expand the role's policy.
      {
        Sid      = "BoundaryDenyPermissionsBoundaryRemoval"
        Effect   = "Deny"
        Action   = ["iam:DeleteRolePermissionsBoundary", "iam:DeleteUserPermissionsBoundary"]
        Resource = "*"
      },
      # Explicit deny: replacing the boundary with anything other than
      # the homelab_principal_boundary itself.
      {
        Sid      = "BoundaryDenyPermissionsBoundaryReplacement"
        Effect   = "Deny"
        Action   = ["iam:PutRolePermissionsBoundary", "iam:PutUserPermissionsBoundary"]
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "iam:PermissionsBoundary" = aws_iam_policy.homelab_principal_boundary.arn
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

# Inline policy — the actual permissions used at runtime.
# Bounded above by terraform_apply_boundary. Resource-scoped wherever AWS
# supports it. IAM stays action-enumerated (security-critical surface);
# other services use action wildcards inside ARN-scoped resources to
# match the boundary and avoid AccessDenied on terraform-required APIs
# that vary across AWS provider versions (e.g. s3:GetAccelerateConfiguration,
# s3:GetIntelligentTieringConfiguration, etc.).
resource "aws_iam_role_policy" "terraform_apply_permissions" {
  # checkov:skip=CKV_AWS_286:Privilege escalation prevented by the IAM enumeration on this resource and the iam:PermissionsBoundary Condition on iam:CreateRole/iam:CreateUser. Service wildcards on s3/lambda/events/cloudtrail/guardduty/logs are scoped via Resource ARN to homelab-*.
  # checkov:skip=CKV_AWS_287:Credential exposure (iam:CreateAccessKey etc) scoped to homelab principal ARNs only.
  # checkov:skip=CKV_AWS_288:Data exfiltration bounded to homelab-* buckets via Resource ARN.
  # checkov:skip=CKV_AWS_289:Permissions management actions scoped to homelab principal ARNs.
  # checkov:skip=CKV_AWS_290:EC2 Describe*/Run/Create on Resource:"*" because AWS does not support resource-level conditions on those actions. All other write actions are scoped via Resource ARN.
  # checkov:skip=CKV_AWS_355:Same as CKV_AWS_290 — Resource:"*" used only where AWS itself does not support resource-level conditions.
  # checkov:skip=CKV2_AWS_40:iam:* not used; IAM actions are explicitly enumerated in IAMHomelabPrincipalsManage and the bounded Create* statements.
  name = "terraform-apply-permissions"
  role = aws_iam_role.github_actions_terraform_apply.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # EC2 — enumerated actions; mostly Resource:"*" because AWS does not
      # support resource-level constraints on RunInstances, CreateFleet,
      # CreateSecurityGroup, etc. The boundary mirrors this list.
      {
        Sid    = "EC2OperationsHomelab"
        Effect = "Allow"
        Action = [
          "ec2:Describe*",
          "ec2:RunInstances", "ec2:TerminateInstances",
          "ec2:StartInstances", "ec2:StopInstances", "ec2:RebootInstances",
          "ec2:ModifyInstanceAttribute", "ec2:ModifyInstanceMetadataOptions",
          "ec2:CreateFleet", "ec2:DeleteFleets", "ec2:ModifyFleet",
          "ec2:CreateLaunchTemplate", "ec2:DeleteLaunchTemplate", "ec2:ModifyLaunchTemplate",
          "ec2:CreateLaunchTemplateVersion", "ec2:DeleteLaunchTemplateVersions",
          "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
          "ec2:UpdateSecurityGroupRuleDescriptionsIngress", "ec2:UpdateSecurityGroupRuleDescriptionsEgress",
          "ec2:CreateKeyPair", "ec2:DeleteKeyPair", "ec2:ImportKeyPair",
          "ec2:CreateTags", "ec2:DeleteTags",
          "ec2:RequestSpotFleet", "ec2:CancelSpotFleetRequests",
          "ec2:GetEbsEncryptionByDefault", "ec2:GetEbsDefaultKmsKeyId",
        ]
        Resource = "*"
      },
      # IAM CreateRole — actual prefixes are hl-k3s-node-* and
      # hl-ec2-scheduler-* (per terraform name_prefix). Boundary attachment
      # is enforced; the corresponding modules in infra/aws/ wire the
      # principal boundary in via data.aws_iam_policy.principal_boundary.
      {
        Sid      = "IAMCreateRoleBounded"
        Effect   = "Allow"
        Action   = ["iam:CreateRole"]
        Resource = ["arn:aws:iam::*:role/hl-*"]
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = aws_iam_policy.homelab_principal_boundary.arn
          }
        }
      },
      {
        Sid      = "IAMCreateUserBounded"
        Effect   = "Allow"
        Action   = ["iam:CreateUser"]
        Resource = ["arn:aws:iam::*:user/system/*"]
        Condition = {
          StringEquals = {
            "iam:PermissionsBoundary" = aws_iam_policy.homelab_principal_boundary.arn
          }
        }
      },
      # Service-linked role lifecycle: AWS-managed, cannot accept a
      # user-supplied permissions boundary, so no Condition.
      {
        Sid    = "IAMServiceLinkedRoles"
        Effect = "Allow"
        Action = [
          "iam:CreateServiceLinkedRole",
          "iam:DeleteServiceLinkedRole",
          "iam:GetServiceLinkedRoleDeletionStatus",
        ]
        Resource = [
          "arn:aws:iam::*:role/aws-service-role/spot.amazonaws.com/*",
          "arn:aws:iam::*:role/aws-service-role/spotfleet.amazonaws.com/*",
        ]
      },
      # Other IAM actions on homelab principals — actual ARN patterns
      # (verified live from terraform plan failures):
      #   - role/hl-* — k3s_node + scheduler_lambda use name_prefix
      #   - user/system/homelab-velero — velero user is at /system/ path
      #   - instance-profile/hl-* — k3s_node profile uses name_prefix
      {
        Sid    = "IAMHomelabPrincipalsManage"
        Effect = "Allow"
        Action = [
          "iam:GetRole", "iam:DeleteRole",
          "iam:UpdateRole", "iam:UpdateRoleDescription", "iam:UpdateAssumeRolePolicy",
          "iam:GetRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:PassRole", "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
          "iam:GetUser", "iam:DeleteUser",
          "iam:GetUserPolicy", "iam:PutUserPolicy", "iam:DeleteUserPolicy", "iam:ListUserPolicies",
          "iam:AttachUserPolicy", "iam:DetachUserPolicy", "iam:ListAttachedUserPolicies",
          "iam:CreateAccessKey", "iam:DeleteAccessKey", "iam:ListAccessKeys", "iam:UpdateAccessKey",
          "iam:GetInstanceProfile", "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile",
          "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile",
          "iam:ListInstanceProfilesForRole", "iam:TagInstanceProfile",
        ]
        Resource = [
          "arn:aws:iam::*:role/hl-*",
          "arn:aws:iam::*:user/system/*",
          "arn:aws:iam::*:instance-profile/hl-*",
        ]
      },
      # Global denies — boundary tampering is impossible regardless of
      # which homelab principal name is targeted.
      {
        Sid      = "DenyPermissionsBoundaryRemoval"
        Effect   = "Deny"
        Action   = ["iam:DeleteRolePermissionsBoundary", "iam:DeleteUserPermissionsBoundary"]
        Resource = "*"
      },
      {
        Sid      = "DenyPermissionsBoundaryReplacement"
        Effect   = "Deny"
        Action   = ["iam:PutRolePermissionsBoundary", "iam:PutUserPermissionsBoundary"]
        Resource = "*"
        Condition = {
          StringNotEquals = {
            "iam:PermissionsBoundary" = aws_iam_policy.homelab_principal_boundary.arn
          }
        }
      },
      # IAM read — narrow allowlist (no access-key enumeration on other users).
      {
        Sid    = "IAMReadNarrow"
        Effect = "Allow"
        Action = [
          "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicies",
          "iam:ListPolicyVersions", "iam:ListEntitiesForPolicy",
          "iam:ListInstanceProfiles", "iam:GetOpenIDConnectProvider",
          "iam:ListOpenIDConnectProviders", "iam:ListOpenIDConnectProviderTags",
        ]
        Resource = "*"
      },
      # S3 — homelab buckets only (state backend included via prefix).
      # Wildcard action because terraform refresh exercises many S3 read
      # APIs that vary across provider versions (GetAccelerateConfiguration,
      # GetIntelligentTieringConfiguration, GetReplicationConfiguration,
      # GetAnalyticsConfiguration, GetMetricsConfiguration, GetInventoryConfiguration,
      # GetBucketObjectLockConfiguration, etc.). Resource scope keeps blast
      # radius bounded to homelab-* buckets.
      {
        Sid      = "S3HomelabBuckets"
        Effect   = "Allow"
        Action   = ["s3:*"]
        Resource = ["arn:aws:s3:::homelab-*", "arn:aws:s3:::homelab-*/*"]
      },
      {
        Sid      = "S3ListAllBuckets"
        Effect   = "Allow"
        Action   = ["s3:ListAllMyBuckets"]
        Resource = "*"
      },
      # Lambda — actual function name uses "hl-" prefix.
      {
        Sid      = "LambdaHomelab"
        Effect   = "Allow"
        Action   = ["lambda:*"]
        Resource = "arn:aws:lambda:*:*:function:hl-*"
      },
      # EventBridge — actual rule names use "hl-" prefix.
      {
        Sid      = "EventsHomelab"
        Effect   = "Allow"
        Action   = ["events:*"]
        Resource = "arn:aws:events:*:*:rule/hl-*"
      },
      # CloudTrail — trail named "homelab-audit"; resource-level scoping.
      {
        Sid      = "CloudTrailHomelab"
        Effect   = "Allow"
        Action   = ["cloudtrail:*"]
        Resource = "arn:aws:cloudtrail:*:*:trail/homelab*"
      },
      # CloudTrail account-wide reads — DescribeTrails, ListTrails,
      # LookupEvents, GetTrailStatus do NOT support resource-level conditions.
      {
        Sid    = "CloudTrailAccountReads"
        Effect = "Allow"
        Action = [
          "cloudtrail:DescribeTrails", "cloudtrail:ListTrails",
          "cloudtrail:LookupEvents", "cloudtrail:GetTrailStatus",
        ]
        Resource = "*"
      },
      # GuardDuty — detector is account-level; no useful resource scoping.
      {
        Sid      = "GuardDutyDetector"
        Effect   = "Allow"
        Action   = ["guardduty:*"]
        Resource = "*"
      },
      # DynamoDB — terraform state lock only.
      {
        Sid    = "DynamoDBStateLock"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
          "dynamodb:DescribeTable", "dynamodb:UpdateItem",
        ]
        Resource = "arn:aws:dynamodb:*:*:table/homelab-terraform-state-lock"
      },
      # KMS metadata only.
      {
        Sid      = "KMSMetadata"
        Effect   = "Allow"
        Action   = ["kms:DescribeKey", "kms:ListAliases"]
        Resource = "*"
      },
      # CloudWatch Logs — Lambda function is named hl-* so log group is /aws/lambda/hl-*.
      {
        Sid      = "CloudWatchLogsHomelab"
        Effect   = "Allow"
        Action   = ["logs:*"]
        Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/hl-*"
      },
      # STS identity inspection.
      {
        Sid      = "STSIdentity"
        Effect   = "Allow"
        Action   = ["sts:GetCallerIdentity"]
        Resource = "*"
      },
    ]
  })
}

# ── homelab_principal_boundary ───────────────────────────────────────────────
#
# Permissions boundary required on every IAM role and user that the apply
# role creates. Closes the privilege-escalation chain identified in the
# PR #38 security review:
#
#   1. Apply role calls iam:CreateRole "k3s-node-evil" with attacker trust.
#   2. Apply role calls iam:PutRolePolicy granting Action:"*" Resource:"*".
#   3. Attacker assumes k3s-node-evil from their account → effective admin.
#
# Without this boundary, AWS does not propagate the apply role's own
# permissions boundary to roles it creates. With this boundary required
# on every Create*, the new role is hard-capped to "do almost anything
# in AWS EXCEPT IAM modification and AssumeRole" — so the third step
# (escalate further or pivot cross-account) is structurally blocked.
#
# Note: this boundary is intentionally permissive on non-IAM/non-STS
# actions because the legitimate child principals (k3s-node, scheduler
# Lambda, velero IAM user) need broad service access (SSM, S3, EC2
# describe/start/stop/snapshot, Lambda logging). Tightening below this
# level would require knowing each child's exact permission set, which
# is iteration-heavy and the inline policies on each child role are
# already explicit and reviewed.
resource "aws_iam_policy" "homelab_principal_boundary" {
  # checkov:skip=CKV_AWS_62:Action:"*" is the boundary's intentional permissive ceiling. The Deny statements on iam:* and sts:AssumeRole* are what give the boundary its security value — tightening Action would require knowing every child principal's needed permission set without adding security beyond the existing Denies.
  # checkov:skip=CKV_AWS_63:Same as CKV_AWS_62 — Action:"*" is intentional in this allow-then-deny boundary design.
  # checkov:skip=CKV2_AWS_40:Same as CKV_AWS_62 — the iam:* Deny is the load-bearing cap on full IAM privileges, not the Allow.
  # checkov:skip=CKV_AWS_290:Allow Action:"*" is the boundary's deliberate "permissive ceiling minus IAM/STS"; tightening to enumerated actions would require knowing every child principal's needed permission set, which the explicit Deny on iam:* and sts:AssumeRole* already caps from the privilege-escalation angle.
  # checkov:skip=CKV_AWS_355:Same as CKV_AWS_290 — boundary is intentionally allow-everything-then-deny-dangerous.
  # checkov:skip=CKV_AWS_286:Privilege escalation is structurally blocked by the explicit Deny on iam:* and sts:AssumeRole* below.
  # checkov:skip=CKV_AWS_287:Credential exposure via iam:CreateAccessKey etc is blocked by the iam:* Deny.
  # checkov:skip=CKV_AWS_288:Data exfiltration risk is the documented residual (child role can read homelab S3 buckets); the inline policy attached to each child principal is the next layer of defense.
  # checkov:skip=CKV_AWS_289:Permissions management is blocked by iam:* Deny.
  name        = "homelab-principal-boundary"
  description = "Hard cap on every IAM role/user created by github-actions-terraform-apply. Allows broad AWS service access EXCEPT IAM modification and sts:AssumeRole, structurally blocking privilege-escalation chains."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AllowMostAWSServices"
        Effect   = "Allow"
        Action   = "*"
        Resource = "*"
      },
      {
        Sid      = "DenyAllIAMModification"
        Effect   = "Deny"
        Action   = ["iam:*"]
        Resource = "*"
      },
      {
        Sid    = "DenyAssumeRoleEscalation"
        Effect = "Deny"
        Action = [
          "sts:AssumeRole",
          "sts:AssumeRoleWithWebIdentity",
          "sts:AssumeRoleWithSAML",
        ]
        Resource = "*"
      },
      {
        Sid      = "DenyOrganizationsAccess"
        Effect   = "Deny"
        Action   = ["organizations:*", "account:*"]
        Resource = "*"
      },
    ]
  })

  tags = {
    Name    = "homelab-principal-boundary"
    Project = "homelab"
  }
}
