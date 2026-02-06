# ==============================================================================
# AWS Network Module - VPC and Security Groups
# ==============================================================================
# This module manages networking resources for the k3s cluster:
# - Default VPC data source (cost optimization - no new VPC)
# - Security groups for k3s cluster communication
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

# Security Group: k3s Cluster
resource "aws_security_group" "k3s_cluster" {
  name_prefix = "hl-k3s-cluster-"
  description = "Security group for k3s cluster nodes"
  vpc_id      = data.aws_vpc.default.id

  # SSH access
  ingress {
    description = "SSH from allowed CIDRs"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ssh_allowed_cidr
  }

  # k3s API server
  ingress {
    description = "k3s API Server"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = var.k3s_api_allowed_cidr
  }

  # Kubelet metrics
  ingress {
    description = "Kubelet metrics"
    from_port   = 10250
    to_port     = 10250
    protocol    = "tcp"
    self        = true
  }

  # k3s flannel VXLAN
  ingress {
    description = "Flannel VXLAN"
    from_port   = 8472
    to_port     = 8472
    protocol    = "udp"
    self        = true
  }

  # CloudNativePG PostgreSQL (internal only)
  ingress {
    description = "PostgreSQL"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    self        = true
  }

  # Allow all traffic between cluster nodes
  ingress {
    description = "All traffic from cluster nodes"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  # Outbound internet access
  egress {
    description = "Allow all outbound"
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
