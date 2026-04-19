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
  description = "Read-only role for terraform plan in CI. Assumed via OIDC by ariel99gf/homelab."

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github_actions.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:ariel99gf/homelab:*"
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
