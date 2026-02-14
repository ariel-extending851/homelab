# ==============================================================================
# AWS Homelab Infrastructure - Root Configuration
# ==============================================================================
# Architecture: k3s cluster on EC2 Spot Instances with CloudNativePG
# Cost: ~$17.65 USD/month (2× t3.small spot + 40GB gp3 EBS)
#
# Modules:
#   - network: VPC, subnets, security groups
#   - compute: EC2 spot instances, IAM roles, SSH keys
#
# Security: SOPS-encrypted secrets, IMDSv2, EBS encryption
# ==============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    sops = {
      source  = "carlpett/sops"
      version = "~> 0.7.0"
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
# Compute Module - k3s Cluster Nodes
# ==============================================================================
module "k3s_cluster" {
  source = "./modules/compute"

  instance_type     = var.instance_type
  ebs_volume_size   = var.ebs_volume_size
  spot_max_price    = var.spot_max_price
  ssh_key_name      = var.ssh_key_name
  ssh_public_key    = local.secrets["ssh_public_key"]
  security_group_id = module.network.security_group_id
  localstack_test   = var.localstack_test

  k3s_token          = local.secrets["k3s_token"]
  k3s_version        = var.k3s_version
  tailscale_auth_key = local.secrets["tailscale_auth_key"]
}
