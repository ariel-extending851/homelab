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

    # Scoped to Velero's own prefix so the cluster-state rule below can apply
    # its own (shorter) retention without this catch-all tiering it to Glacier.
    filter {
      prefix = "backups/"
    }

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

  # k3s control-plane (SQLite) snapshots uploaded by the k8s/apps/k3s-snapshot
  # CronJob. Small (tens of MB gzipped) and meant for fast restore, so they
  # stay in Standard and expire at 30 days — no IA/Glacier tiering.
  rule {
    id     = "expire-cluster-state-snapshots"
    status = "Enabled"

    filter {
      prefix = "cluster-state/"
    }

    expiration {
      days = 30
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
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

# ==============================================================================
# IAM user for the k3s control-plane snapshot CronJob — WRITE-ONLY, prefix-scoped
# ==============================================================================
# The k8s/apps/k3s-snapshot CronJob on rasp-pi-04 uploads gzipped SQLite
# snapshots of the k3s datastore to the cluster-state/ prefix of the Velero
# bucket. This closes the real DR gap: with cluster-init=false the k3s
# etcd-snapshot config is inert (SQLite), so there is no automated control-plane
# backup — Velero only covers app namespaces + PVCs, not the datastore.
#
# Separate user (not Velero's) for a different blast radius and rotation cadence.
# Write-only on cluster-state/* (no GetObject/DeleteObject): a compromised Pi pod
# can append a snapshot but cannot read or wipe backup history. Restore is a
# human operator action using admin credentials — see
# docs/runbooks/control-plane-snapshot-restore-pi.md.
#
# Path /system/ matches the OIDC apply-role allowlist (user/system/*), so this
# needs no infra/aws-oidc change.
resource "aws_iam_user" "k3s_snapshot" {
  name                 = "hl-k3s-snapshot"
  path                 = "/system/"
  permissions_boundary = data.aws_iam_policy.principal_boundary.arn

  tags = {
    Name    = "hl-k3s-snapshot"
    Purpose = "k3s control-plane SQLite snapshot uploader"
  }
}

resource "aws_iam_access_key" "k3s_snapshot" {
  user = aws_iam_user.k3s_snapshot.name
}

resource "aws_iam_user_policy" "k3s_snapshot_access" {
  name = "k3s-snapshot-cluster-state-write"
  user = aws_iam_user.k3s_snapshot.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteSnapshots"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:AbortMultipartUpload",
          "s3:ListMultipartUploadParts",
        ]
        Resource = "${aws_s3_bucket.velero_backups.arn}/cluster-state/*"
      },
      {
        Sid    = "ListOwnPrefixOnly"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:ListBucketMultipartUploads",
        ]
        Resource = aws_s3_bucket.velero_backups.arn
        Condition = {
          StringLike = {
            "s3:prefix" = "cluster-state/*"
          }
        }
      },
    ]
  })
}
