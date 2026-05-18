# /infra/aws-velero/main.tf
#
# AWS Lite — the always-on slice of the homelab's AWS footprint.
#
# WHY THIS EXISTS as its own module (separate from infra/aws/):
#   The full hybrid stack (EC2 fleets + Lambda scheduler + observability)
#   in infra/aws/ is designed to be `terraform destroy`-able for cost
#   reasons (~$24/mo). But cluster backups (Velero → S3) need to outlive
#   those teardowns: when the EC2s sleep on the scheduler, when the user
#   destroys the hybrid stack to save money, when there is no AWS cluster
#   at all. So Velero's bucket + IAM user live here, applied once and left
#   alone. Cost envelope: ~$0.50–$2/mo depending on backup volume
#   (Standard → IA after 30d → Glacier after 90d via lifecycle policy).
#
# Pattern mirrors infra/aws-backend/ and infra/aws-oidc/ — small, surgical,
# rarely touched. Uses the same S3 state bucket as infra/aws/ via a
# different key so `terraform destroy` in infra/aws/ does not nuke this
# module's state.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket       = "homelab-terraform-state-kkuhocyv"
    key          = "homelab/velero.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "homelab"
      Environment = "Prod"
      Service     = "velero-backups"
      ManagedBy   = "Terraform"
    }
  }
}

# Look up the IAM permissions boundary created by infra/aws-oidc/. Required
# on every IAM user/role created by this account's principals to satisfy
# the privilege-escalation lock added in PR #38.
data "aws_iam_policy" "principal_boundary" {
  name = "homelab-principal-boundary"
}

locals {
  bucket_name = "homelab-velero-backups-kkuhocyv"
}

# ==============================================================================
# S3 Bucket for Velero Cluster Backups
# ==============================================================================
# Stores k3s backup archives (resources, configmaps, PVCs) uploaded by Velero.
# Lifecycle: Standard → IA after 30d → Glacier after 90d → expire after 365d.
# Versioned for point-in-time restore, encrypted at rest.
# tfsec:ignore:aws-s3-enable-bucket-logging
resource "aws_s3_bucket" "velero_backups" {
  bucket        = local.bucket_name
  force_destroy = false # backups are precious — opt-out of accidental deletion

  tags = {
    Name    = local.bucket_name
    Purpose = "Velero cluster backup storage"
  }
}

resource "aws_s3_bucket_versioning" "velero_backups" {
  bucket = aws_s3_bucket.velero_backups.id
  versioning_configuration {
    status = "Enabled"
  }
}

# tfsec:ignore:aws-s3-encryption-customer-key
resource "aws_s3_bucket_server_side_encryption_configuration" "velero_backups" {
  bucket = aws_s3_bucket.velero_backups.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "velero_backups" {
  bucket = aws_s3_bucket.velero_backups.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "velero_backups" {
  bucket = aws_s3_bucket.velero_backups.id

  rule {
    id     = "tier-and-expire-old-backups"
    status = "Enabled"

    filter {}

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 365
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# ==============================================================================
# IAM user for Velero — least-privilege scoped to the bucket above.
# ==============================================================================
# Static credentials are required because k3s does not have an OIDC provider
# for IRSA. The access key pair is read from terraform outputs and then
# encrypted into k8s/apps/velero/secret.yaml via SOPS (one-time chore after
# `terraform apply`).
resource "aws_iam_user" "velero" {
  name                 = "homelab-velero"
  path                 = "/system/"
  permissions_boundary = data.aws_iam_policy.principal_boundary.arn

  tags = {
    Name    = "homelab-velero"
    Purpose = "Velero backup uploader"
  }
}

resource "aws_iam_access_key" "velero" {
  user = aws_iam_user.velero.name
}

resource "aws_iam_user_policy" "velero_backup_access" {
  name = "velero-backup-bucket-access"
  user = aws_iam_user.velero.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
        ]
        Resource = "${aws_s3_bucket.velero_backups.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:ListBucketMultipartUploads",
        ]
        Resource = aws_s3_bucket.velero_backups.arn
      },
    ]
  })
}
