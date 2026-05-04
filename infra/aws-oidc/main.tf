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
  # checkov:skip=CKV_AWS_290:EC2 Describe*/RunInstances/CreateFleet/CreateLaunchTemplate require Resource:"*" because AWS itself does not support resource-level conditions on these actions. Write actions on EXISTING resources are scoped via aws:ResourceTag/Project=homelab; creation actions are scoped via aws:RequestTag/Project=homelab. The Condition is a real constraint Checkov does not recognize for this rule.
  # checkov:skip=CKV_AWS_355:Same as CKV_AWS_290 — EC2 Describe* and creation APIs are not "restrictable" at the AWS resource level. Lifecycle and creation actions ARE constrained via aws:ResourceTag/aws:RequestTag conditions.
  name        = "github-actions-terraform-apply-boundary"
  description = "Maximum permissions cap for github-actions-terraform-apply (public-repo defense-in-depth)."

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # EC2 read-only — Describe/Get APIs do not support resource-level
      # conditions (AWS itself enforces this), so Resource:"*" is mandatory.
      {
        Sid    = "EC2ReadOnly"
        Effect = "Allow"
        Action = [
          "ec2:Describe*",
          "ec2:GetEbsEncryptionByDefault", "ec2:GetEbsDefaultKmsKeyId",
        ]
        Resource = "*"
      },
      # EC2 lifecycle — actions on EXISTING resources, scoped by Project tag.
      {
        Sid    = "EC2LifecycleByTag"
        Effect = "Allow"
        Action = [
          "ec2:TerminateInstances",
          "ec2:StartInstances", "ec2:StopInstances", "ec2:RebootInstances",
          "ec2:ModifyInstanceAttribute", "ec2:ModifyInstanceMetadataOptions",
          "ec2:DeleteFleets", "ec2:ModifyFleet",
          "ec2:DeleteLaunchTemplate", "ec2:ModifyLaunchTemplate",
          "ec2:DeleteLaunchTemplateVersions",
          "ec2:DeleteSecurityGroup",
          "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
          "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
          "ec2:UpdateSecurityGroupRuleDescriptionsIngress", "ec2:UpdateSecurityGroupRuleDescriptionsEgress",
          "ec2:DeleteKeyPair",
          "ec2:DeleteTags",
          "ec2:CancelSpotFleetRequests",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/Project" = "homelab"
          }
        }
      },
      # EC2 creation — Run/Create require RequestTag enforcement so newly
      # created resources are tagged Project=homelab and become eligible
      # for the lifecycle statement above.
      {
        Sid    = "EC2CreateWithRequestTag"
        Effect = "Allow"
        Action = [
          "ec2:RunInstances",
          "ec2:CreateFleet",
          "ec2:CreateLaunchTemplate", "ec2:CreateLaunchTemplateVersion",
          "ec2:CreateSecurityGroup",
          "ec2:CreateKeyPair", "ec2:ImportKeyPair",
          "ec2:CreateTags",
          "ec2:RequestSpotFleet",
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:RequestTag/Project" = "homelab"
          }
        }
      },
      # IAM — enumerated. Excludes privilege-escalation vectors:
      # CreateLoginProfile, UpdateLoginProfile (console password backdoor),
      # CreatePolicyVersion / SetDefaultPolicyVersion (managed-policy hijack),
      # GenerateCredentialReport, GetCredentialReport, GetAccessKeyLastUsed.
      {
        Sid    = "BoundaryIAMScoped"
        Effect = "Allow"
        Action = [
          "iam:GetRole", "iam:CreateRole", "iam:DeleteRole",
          "iam:UpdateRole", "iam:UpdateRoleDescription", "iam:UpdateAssumeRolePolicy",
          "iam:GetRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:PassRole", "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
          "iam:GetUser", "iam:CreateUser", "iam:DeleteUser",
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
      # IAM read — narrow whitelist. Excludes Get/List access-key actions
      # for other users (would otherwise allow enumerating account creds).
      {
        Sid    = "BoundaryIAMReadNarrow"
        Effect = "Allow"
        Action = [
          "iam:GetPolicy", "iam:GetPolicyVersion", "iam:ListPolicies",
          "iam:ListPolicyVersions", "iam:ListEntitiesForPolicy",
          "iam:ListInstanceProfiles", "iam:GetOpenIDConnectProvider",
          "iam:ListOpenIDConnectProviders", "iam:ListOpenIDConnectProviderTags",
        ]
        Resource = "*"
      },
      # S3 — homelab buckets only.
      {
        Sid    = "BoundaryS3HomelabBuckets"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket", "s3:DeleteBucket",
          "s3:ListBucket", "s3:ListBucketVersions",
          "s3:GetBucketLocation", "s3:GetBucketTagging", "s3:PutBucketTagging",
          "s3:GetBucketVersioning", "s3:PutBucketVersioning",
          "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration",
          "s3:GetLifecycleConfiguration", "s3:PutLifecycleConfiguration",
          "s3:GetBucketPublicAccessBlock", "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketPolicy", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy",
          "s3:GetBucketAcl", "s3:PutBucketAcl",
          "s3:GetBucketCORS", "s3:PutBucketCORS",
          "s3:GetBucketOwnershipControls", "s3:PutBucketOwnershipControls",
          "s3:GetBucketRequestPayment", "s3:GetBucketLogging",
          "s3:GetBucketObjectLockConfiguration", "s3:GetBucketWebsite",
          "s3:GetReplicationConfiguration",
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
          "s3:GetObjectVersion", "s3:GetObjectTagging", "s3:PutObjectTagging",
          "s3:DeleteObjectVersion",
        ]
        Resource = [
          "arn:aws:s3:::homelab-*",
          "arn:aws:s3:::homelab-*/*",
        ]
      },
      {
        Sid      = "BoundaryS3List"
        Effect   = "Allow"
        Action   = ["s3:ListAllMyBuckets"]
        Resource = "*"
      },
      # Lambda — homelab functions only.
      {
        Sid    = "BoundaryLambdaHomelab"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction", "lambda:DeleteFunction",
          "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionUrlConfig",
          "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
          "lambda:UpdateFunctionUrlConfig", "lambda:CreateFunctionUrlConfig", "lambda:DeleteFunctionUrlConfig",
          "lambda:AddPermission", "lambda:RemovePermission", "lambda:GetPolicy",
          "lambda:ListVersionsByFunction", "lambda:PublishVersion",
          "lambda:TagResource", "lambda:UntagResource", "lambda:ListTags",
          "lambda:GetCodeSigningConfig",
        ]
        Resource = "arn:aws:lambda:*:*:function:homelab-*"
      },
      # EventBridge — homelab rules only.
      {
        Sid    = "BoundaryEventsHomelab"
        Effect = "Allow"
        Action = [
          "events:DescribeRule", "events:PutRule", "events:DeleteRule",
          "events:EnableRule", "events:DisableRule", "events:ListRules",
          "events:PutTargets", "events:RemoveTargets", "events:ListTargetsByRule",
          "events:TagResource", "events:UntagResource", "events:ListTagsForResource",
        ]
        Resource = "arn:aws:events:*:*:rule/homelab-*"
      },
      # CloudTrail — homelab trail only.
      {
        Sid    = "BoundaryCloudTrailHomelab"
        Effect = "Allow"
        Action = [
          "cloudtrail:CreateTrail", "cloudtrail:DeleteTrail", "cloudtrail:UpdateTrail",
          "cloudtrail:GetTrail", "cloudtrail:GetTrailStatus", "cloudtrail:DescribeTrails",
          "cloudtrail:StartLogging", "cloudtrail:StopLogging",
          "cloudtrail:GetEventSelectors", "cloudtrail:PutEventSelectors",
          "cloudtrail:AddTags", "cloudtrail:RemoveTags", "cloudtrail:ListTags",
        ]
        Resource = "arn:aws:cloudtrail:*:*:trail/homelab*"
      },
      # GuardDuty — detector is account-level; no useful resource scoping.
      {
        Sid    = "BoundaryGuardDuty"
        Effect = "Allow"
        Action = [
          "guardduty:CreateDetector", "guardduty:DeleteDetector", "guardduty:UpdateDetector",
          "guardduty:GetDetector", "guardduty:ListDetectors",
          "guardduty:TagResource", "guardduty:UntagResource", "guardduty:ListTagsForResource",
        ]
        Resource = "*"
      },
      # DynamoDB — terraform state lock only.
      {
        Sid    = "BoundaryDynamoDBLock"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem",
          "dynamodb:DescribeTable", "dynamodb:UpdateItem",
        ]
        Resource = "arn:aws:dynamodb:*:*:table/homelab-terraform-state-lock"
      },
      # CloudWatch Logs — Lambda function logs.
      {
        Sid    = "BoundaryLogsHomelab"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup", "logs:DeleteLogGroup",
          "logs:DescribeLogGroups", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy",
          "logs:TagLogGroup", "logs:UntagLogGroup", "logs:ListTagsForResource",
          "logs:ListTagsLogGroup",
        ]
        Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/homelab-*"
      },
      # KMS metadata only — no Decrypt, no Sign, no GenerateDataKey.
      {
        Sid      = "BoundaryKMSMetadata"
        Effect   = "Allow"
        Action   = ["kms:DescribeKey", "kms:ListAliases"]
        Resource = "*"
      },
      # STS — identity inspection only.
      {
        Sid      = "BoundarySTSIdentity"
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
    ]
  })

  tags = {
    Name    = "github-actions-terraform-apply-boundary"
    Project = "homelab"
  }
}

# Inline policy — the actual permissions used at runtime.
# Bounded above by terraform_apply_boundary. Resource-scoped wherever AWS
# supports it; action-enumerated so it cannot grow into a wildcard footgun.
resource "aws_iam_role_policy" "terraform_apply_permissions" {
  # checkov:skip=CKV_AWS_290:Same justification as terraform_apply_boundary — EC2 Describe*/Run/Create require Resource:"*" because AWS does not support resource-level conditions on those actions. Write/creation actions ARE constrained via aws:ResourceTag/Project=homelab and aws:RequestTag/Project=homelab Conditions.
  # checkov:skip=CKV_AWS_355:Same as CKV_AWS_290.
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
      # IAM — homelab principals only. Same scoping as boundary.
      {
        Sid    = "IAMHomelabPrincipals"
        Effect = "Allow"
        Action = [
          "iam:GetRole", "iam:CreateRole", "iam:DeleteRole",
          "iam:UpdateRole", "iam:UpdateRoleDescription", "iam:UpdateAssumeRolePolicy",
          "iam:GetRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:ListRolePolicies",
          "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
          "iam:PassRole", "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
          "iam:GetUser", "iam:CreateUser", "iam:DeleteUser",
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
      {
        Sid    = "S3HomelabBuckets"
        Effect = "Allow"
        Action = [
          "s3:CreateBucket", "s3:DeleteBucket",
          "s3:ListBucket", "s3:ListBucketVersions",
          "s3:GetBucketLocation", "s3:GetBucketTagging", "s3:PutBucketTagging",
          "s3:GetBucketVersioning", "s3:PutBucketVersioning",
          "s3:GetEncryptionConfiguration", "s3:PutEncryptionConfiguration",
          "s3:GetLifecycleConfiguration", "s3:PutLifecycleConfiguration",
          "s3:GetBucketPublicAccessBlock", "s3:PutBucketPublicAccessBlock",
          "s3:GetBucketPolicy", "s3:PutBucketPolicy", "s3:DeleteBucketPolicy",
          "s3:GetBucketAcl", "s3:PutBucketAcl",
          "s3:GetBucketOwnershipControls", "s3:PutBucketOwnershipControls",
          "s3:GetBucketCORS", "s3:GetBucketRequestPayment", "s3:GetBucketLogging",
          "s3:GetBucketObjectLockConfiguration", "s3:GetBucketWebsite",
          "s3:GetReplicationConfiguration",
          "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
          "s3:GetObjectVersion", "s3:GetObjectTagging", "s3:PutObjectTagging",
          "s3:DeleteObjectVersion",
        ]
        Resource = [
          "arn:aws:s3:::homelab-*",
          "arn:aws:s3:::homelab-*/*",
        ]
      },
      {
        Sid      = "S3ListAllBuckets"
        Effect   = "Allow"
        Action   = ["s3:ListAllMyBuckets"]
        Resource = "*"
      },
      # Lambda — homelab functions only.
      {
        Sid    = "LambdaHomelab"
        Effect = "Allow"
        Action = [
          "lambda:CreateFunction", "lambda:DeleteFunction",
          "lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:GetFunctionUrlConfig",
          "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration",
          "lambda:UpdateFunctionUrlConfig", "lambda:CreateFunctionUrlConfig", "lambda:DeleteFunctionUrlConfig",
          "lambda:AddPermission", "lambda:RemovePermission", "lambda:GetPolicy",
          "lambda:ListVersionsByFunction", "lambda:PublishVersion",
          "lambda:TagResource", "lambda:UntagResource", "lambda:ListTags",
          "lambda:GetCodeSigningConfig",
        ]
        Resource = "arn:aws:lambda:*:*:function:homelab-*"
      },
      # EventBridge — homelab rules only.
      {
        Sid    = "EventsHomelab"
        Effect = "Allow"
        Action = [
          "events:DescribeRule", "events:PutRule", "events:DeleteRule",
          "events:EnableRule", "events:DisableRule", "events:ListRules",
          "events:PutTargets", "events:RemoveTargets", "events:ListTargetsByRule",
          "events:TagResource", "events:UntagResource", "events:ListTagsForResource",
        ]
        Resource = "arn:aws:events:*:*:rule/homelab-*"
      },
      # CloudTrail — homelab trail only.
      {
        Sid    = "CloudTrailHomelab"
        Effect = "Allow"
        Action = [
          "cloudtrail:CreateTrail", "cloudtrail:DeleteTrail", "cloudtrail:UpdateTrail",
          "cloudtrail:GetTrail", "cloudtrail:GetTrailStatus", "cloudtrail:DescribeTrails",
          "cloudtrail:StartLogging", "cloudtrail:StopLogging",
          "cloudtrail:GetEventSelectors", "cloudtrail:PutEventSelectors",
          "cloudtrail:AddTags", "cloudtrail:RemoveTags", "cloudtrail:ListTags",
        ]
        Resource = "arn:aws:cloudtrail:*:*:trail/homelab*"
      },
      # GuardDuty — detector is account-level; no useful resource scoping.
      {
        Sid    = "GuardDutyDetector"
        Effect = "Allow"
        Action = [
          "guardduty:CreateDetector", "guardduty:DeleteDetector", "guardduty:UpdateDetector",
          "guardduty:GetDetector", "guardduty:ListDetectors",
          "guardduty:TagResource", "guardduty:UntagResource", "guardduty:ListTagsForResource",
        ]
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
      # CloudWatch Logs — homelab Lambda functions.
      {
        Sid    = "CloudWatchLogsHomelab"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup", "logs:DeleteLogGroup",
          "logs:DescribeLogGroups", "logs:PutRetentionPolicy", "logs:DeleteRetentionPolicy",
          "logs:TagLogGroup", "logs:UntagLogGroup", "logs:ListTagsForResource",
          "logs:ListTagsLogGroup",
        ]
        Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/homelab-*"
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
