# ==============================================================================
# AWS Homelab Infrastructure - Root Configuration
# ==============================================================================
# Architecture: k3s cluster on EC2 Spot Instances (t3.medium server + t3.small agent, 30 GB gp3 EBS each)
# Cost: ~$24.59/month with scheduling, ~$45.55/month 24/7 (computed in outputs.tf:68-71)
# See: docs/architecture/aws-infrastructure.md, docs/operations/cost-and-scheduling.md
#
# Modules:
#   - network:   VPC, subnets, security group (Zero Trust — no public ingress)
#   - compute:   EC2 spot instances, IAM, SSH key, k3s install user-data
#   - scheduler: Lambda + EventBridge for daily start/stop (10:00 / 21:00 BRT)
#
# Security: SOPS-encrypted secrets, IMDSv2 required, EBS encryption
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"

  backend "s3" {
    bucket       = "homelab-terraform-state-kkuhocyv"
    key          = "homelab/terraform.tfstate"
    region       = "us-east-1"
    use_lockfile = true # replaces deprecated dynamodb_table (Terraform >= 1.10)
    encrypt      = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.45"
    }
    sops = {
      source  = "carlpett/sops"
      version = "~> 0.7.0"
    }
    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.13"
    }
  }
}

# SOPS Provider Configuration
provider "sops" {}

# ==============================================================================
# Secrets Configuration
# ==============================================================================
# When localstack_test = "yes": Uses mock secrets (no SOPS decryption needed)
# When localstack_test = "no":  Loads real secrets from SOPS-encrypted file

locals {
  secrets = var.localstack_test == "yes" ? {
    # Use a properly formatted SSH key for LocalStack testing
    # This is a mock key - DO NOT USE IN PRODUCTION
    ssh_public_key     = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC0Z8p0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0Z0 localstack-test"
    k3s_token          = "mock-k3s-token-for-localstack-testing-only-do-not-use-in-production"
    tailscale_auth_key = "tskey-auth-mock-localstack-testing-only"
  } : data.sops_file.secrets.data
}

# Load secrets from SOPS-encrypted file (only used when localstack_test = "no")
data "sops_file" "secrets" {
  source_file = "${path.module}/terraform.tfvars.sops.yaml"
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "Lab-DevOps-Pro"
      ManagedBy   = "Terraform"
      Environment = "homelab"
    }
  }
}

# ==============================================================================
# Network Module
# ==============================================================================
module "network" {
  source = "./modules/network"
  # Zero Trust: No CIDR variables needed - all access via Tailscale mesh
}

# ==============================================================================
# IAM Permissions Boundary for child principals
# ==============================================================================
# Created by infra/aws-oidc/. The github-actions-terraform-apply role REQUIRES
# this boundary on every iam:CreateRole / iam:CreateUser it issues — closes
# the privilege-escalation chain identified in the PR #38 security review.
# Look up by name so we don't have to hardcode the ARN.
data "aws_iam_policy" "principal_boundary" {
  count = var.localstack_test == "no" ? 1 : 0
  name  = "homelab-principal-boundary"
}

locals {
  principal_boundary_arn = var.localstack_test == "no" ? data.aws_iam_policy.principal_boundary[0].arn : null
}

# ==============================================================================
# Compute Module - k3s Cluster Nodes
# ==============================================================================
module "k3s_cluster" {
  source = "./modules/compute"

  server_instance_type = var.server_instance_type
  agent_instance_type  = var.agent_instance_type
  ebs_volume_size      = var.ebs_volume_size
  spot_max_price       = var.spot_max_price
  ssh_key_name         = var.ssh_key_name
  ssh_public_key       = local.secrets["ssh_public_key"]
  security_group_id    = module.network.security_group_id
  localstack_test      = var.localstack_test

  k3s_token          = local.secrets["k3s_token"]
  k3s_version        = var.k3s_version
  tailscale_auth_key = local.secrets["tailscale_auth_key"]

  ssm_s3_bucket = var.ssm_s3_bucket

  principal_boundary_arn = local.principal_boundary_arn
}

# ==============================================================================
# S3 Bucket for SSM Session Manager Transfers
# ==============================================================================
# CRITICAL SECURITY: This bucket is SEPARATE from the Terraform state bucket.
# EC2 instances have read/write access to this bucket for Ansible SSM connections.
# Using the Terraform state bucket would expose decrypted secrets to compromised nodes.
# tfsec:ignore:aws-s3-enable-bucket-logging
resource "aws_s3_bucket" "ssm_transfer" {
  bucket        = var.ssm_s3_bucket
  force_destroy = true

  tags = {
    Name        = "homelab-ssm-transfer"
    Environment = "production"
    Purpose     = "SSM Session Manager file transfer for Ansible"
    ManagedBy   = "Terraform"
  }
}

# Enable versioning for audit trail
resource "aws_s3_bucket_versioning" "ssm_transfer" {
  bucket = aws_s3_bucket.ssm_transfer.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Enable encryption at rest
# tfsec:ignore:aws-s3-encryption-customer-key
resource "aws_s3_bucket_server_side_encryption_configuration" "ssm_transfer" {
  bucket = aws_s3_bucket.ssm_transfer.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Block all public access
resource "aws_s3_bucket_public_access_block" "ssm_transfer" {
  bucket = aws_s3_bucket.ssm_transfer.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle rule: Delete old SSM session logs after 7 days
resource "aws_s3_bucket_lifecycle_configuration" "ssm_transfer" {
  bucket = aws_s3_bucket.ssm_transfer.id

  rule {
    id     = "delete-old-ssm-sessions"
    status = "Enabled"

    # Apply to the whole bucket (required by provider: filter or prefix)
    filter {}

    expiration {
      days = 7
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }
}

# Velero S3 bucket + IAM user moved to infra/aws-velero/ so the backup
# infrastructure survives `terraform destroy` of this hybrid stack.
# Bucket name (`homelab-velero-backups-kkuhocyv`) and IAM user
# (`homelab-velero`) are unchanged; downstream references (Velero
# ConfigMap, k8s/apps/velero/) stay valid regardless of whether this
# module is applied or destroyed.

# ==============================================================================
# Audit Module — CloudTrail + GuardDuty
# ==============================================================================
# Cost envelope <$5/month: management events only, single-region trail,
# GuardDuty SIX_HOURS cadence. See infra/aws/modules/audit/main.tf.
# Skipped under LocalStack (provider lacks CloudTrail/GuardDuty support).
module "audit" {
  source = "./modules/audit"
  count  = var.localstack_test == "no" ? 1 : 0

  aws_region        = var.aws_region
  trail_bucket_name = var.audit_trail_bucket
}

# ==============================================================================
# Scheduler Module - Automated Instance Start/Stop
# ==============================================================================
module "scheduler" {
  source = "./modules/scheduler"
  count  = var.enable_scheduling && var.localstack_test == "no" ? 1 : 0

  server_instance_id = module.k3s_cluster.k3s_server_instance_id
  agent_instance_id  = module.k3s_cluster.k3s_agent_instance_id

  schedule_timezone   = var.schedule_timezone
  schedule_start_hour = var.schedule_start_hour
  schedule_stop_hour  = var.schedule_stop_hour

  principal_boundary_arn = local.principal_boundary_arn
}
