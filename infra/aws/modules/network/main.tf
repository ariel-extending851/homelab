# ==============================================================================
# AWS Network Module - VPC and Security Groups
# ==============================================================================
# This module manages networking resources for the k3s cluster:
# - Default VPC data source (cost optimization - no new VPC)
# - Security groups for k3s cluster communication
#
# ZERO TRUST ARCHITECTURE:
# No public ports are exposed (no SSH, no k3s API ingress).
# All access is through Tailscale mesh (WireGuard encrypted).
# Emergency access via AWS SSM Session Manager (IAM-authenticated).
# ==============================================================================

# Data source: Default VPC
data "aws_vpc" "default" {
  default = true
}

# Data source: Default subnets (for multi-AZ spot flexibility)
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Security Group: k3s Cluster (Zero Trust - no public ingress)
resource "aws_security_group" "k3s_cluster" {
  name_prefix = "hl-k3s-cluster-"
  description = "Zero Trust SG for k3s cluster - no public ingress, all access via Tailscale"
  vpc_id      = data.aws_vpc.default.id

  # ============================================================================
  # INGRESS: Only inter-node traffic (self-referencing)
  # All external access (SSH, kubectl, etc.) goes through Tailscale mesh
  # ============================================================================

  # Allow all traffic between cluster nodes (same SG)
  ingress {
    description = "All traffic between cluster nodes (same SG)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  # ============================================================================
  # EGRESS: Allow outbound (required for Tailscale, ECR, package repos)
  # ============================================================================
  # tfsec:ignore:aws-ec2-no-public-egress-sgr
  egress {
    description = "Allow all outbound (Tailscale, container pulls, updates)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "hl-k3s-cluster-sg"
  }

  lifecycle {
    create_before_destroy = true
  }
}
