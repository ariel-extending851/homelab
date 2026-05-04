# ==============================================================================
# AWS Compute Module - EC2 Spot Instances for k3s
# ==============================================================================
# This module manages compute resources for the k3s cluster:
# - IAM roles and instance profiles
# - SSH key pairs
# - Launch templates
# - Spot instance requests (persistent)
# - EC2 instance tagging
# ==============================================================================

# Data source: Latest Amazon Linux 2023 AMI
data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# SSH Key Pair (skipped in LocalStack test mode due to key format validation)
resource "aws_key_pair" "homelab" {
  count = var.localstack_test == "yes" ? 0 : 1

  key_name   = var.ssh_key_name
  public_key = var.ssh_public_key

  tags = {
    Name = "hl-homelab-key"
  }
}

# IAM Role for EC2 instances (SSM Session Manager support)
resource "aws_iam_role" "k3s_node" {
  name_prefix = "hl-k3s-node-"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "hl-k3s-node-role"
  }
}

# Attach SSM policy for Session Manager
resource "aws_iam_role_policy_attachment" "k3s_node_ssm" {
  role       = aws_iam_role.k3s_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Inline S3 policy — allows SSM Session Manager to use S3 for file transfer
# (Ansible SSM connection plugin requires S3 for stdin/stdout relay)
# ⚠️ SECURITY WARNING: Use a SEPARATE S3 bucket for SSM transfers, NOT the
# Terraform state bucket. The state bucket contains decrypted secrets (k3s_token,
# tailscale_auth_key, etc.). Nodes with this role can read/write to the SSM bucket.
#
# Least-privilege: Only GetObject and PutObject are required for SSM file transfer.
# ListBucket is NOT needed and has been removed to reduce attack surface.
resource "aws_iam_role_policy" "k3s_node_ssm_s3" {
  name = "ssm-s3-transfer"
  role = aws_iam_role.k3s_node.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SSMFileTransfer"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
        ]
        Resource = [
          "arn:aws:s3:::${var.ssm_s3_bucket}/*",
        ]
      }
    ]
  })
}

# Instance profile
resource "aws_iam_instance_profile" "k3s_node" {
  name_prefix = "hl-k3s-node-"
  role        = aws_iam_role.k3s_node.name

  tags = {
    Name = "hl-k3s-node-profile"
  }
}

# Launch template for k3s server node
resource "aws_launch_template" "k3s_server" {
  name_prefix   = "hl-k3s-server-"
  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = var.server_instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.k3s_node.name
  }

  key_name = var.localstack_test == "yes" ? null : aws_key_pair.homelab[0].key_name

  vpc_security_group_ids = [var.security_group_id]

  user_data = base64encode(templatefile("${path.module}/templates/user_data.tftpl", {
    k3s_token          = var.k3s_token
    k3s_version        = var.k3s_version
    node_index         = 1
    node_type          = "server"
    server_hostname    = "" # Not used for server node
    tailscale_auth_key = var.tailscale_auth_key
  }))

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = var.ebs_volume_size
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "hl-k3s-server"
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      Name = "hl-k3s-server-ebs"
    }
  }

  tags = {
    Name = "hl-k3s-server-launch-template"
  }
}

# Launch template for k3s agent node
# The agent resolves the server IP at boot via Tailscale hostname (k3s-server-1),
# eliminating the Terraform timing dependency on the server's dynamic IP.
resource "aws_launch_template" "k3s_agent" {
  name_prefix   = "hl-k3s-agent-"
  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = var.agent_instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.k3s_node.name
  }

  key_name = var.localstack_test == "yes" ? null : aws_key_pair.homelab[0].key_name

  vpc_security_group_ids = [var.security_group_id]

  user_data = base64encode(templatefile("${path.module}/templates/user_data.tftpl", {
    k3s_token          = var.k3s_token
    k3s_version        = var.k3s_version
    node_index         = 2
    node_type          = "agent"
    server_hostname    = "k3s-server-1" # Stable Tailscale hostname — no timing dependency
    tailscale_auth_key = var.tailscale_auth_key
  }))

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = var.ebs_volume_size
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1
  }

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "hl-k3s-agent"
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      Name = "hl-k3s-agent-ebs"
    }
  }

  tags = {
    Name = "hl-k3s-agent-launch-template"
  }
}

# EC2 Fleet for k3s server (single spot instance)
#
# Override list floors at 2 GiB RAM (t3.small) — see postmortem 2026-05-03
# gotcha #3: spot fleet's price-capacity-optimized strategy may substitute the
# launch-template instance_type with the cheapest pool from these overrides.
# Including t3.micro (1 GiB) here let staging silently downsize to a 1 GiB host,
# which OOMs ArgoCD reconcile + breaks SSM exec timeouts. Dropping micros
# keeps the floor at 2 GiB while preserving Intel/AMD diversity for the
# allocation strategy.
resource "aws_ec2_fleet" "k3s_server" {
  launch_template_config {
    launch_template_specification {
      launch_template_id = aws_launch_template.k3s_server.id
      version            = "$Latest"
    }
    override {
      instance_type = "t3.small"
    }
    override {
      instance_type = "t3a.small"
    }
    override {
      instance_type = "t3.medium"
    }
  }

  target_capacity_specification {
    default_target_capacity_type = "spot"
    total_target_capacity        = 1
    spot_target_capacity         = 1
  }

  spot_options {
    allocation_strategy            = "price-capacity-optimized"
    instance_interruption_behavior = "stop"
  }

  terminate_instances                 = true
  terminate_instances_with_expiration = false
  type                                = "maintain"

  # AWS reports instance_pools_to_use_count = 0 in state while the provider
  # default is 1, causing every plan to flag "forces replacement" on the fleet.
  # Postmortem 2026-05-03 (gotcha #4): docs/runbooks/staging-deploy-2026-05-postmortem.md
  lifecycle {
    ignore_changes = [spot_options[0].instance_pools_to_use_count]
  }

  tags = {
    Name = "hl-k3s-server-fleet"
  }
}

# aws_ec2_fleet returns once AWS accepts the request, before instances are
# actually running. Without a wait, the data source below resolves to an empty
# list and propagates "" through the module outputs — terraform_inventory_aws.py
# then sees an empty k3s_agent host group and ansible-deploy fails at "Wait for
# agent to join". Workaround "terraform apply -refresh-only" confirmed live
# during canary 2 (2026-05-04). 60s is the smallest delay that consistently let
# the spot fleet provision both nodes during canary; aws_instance has built-in
# state waiters, aws_ec2_fleet does not.
resource "time_sleep" "wait_server_fleet" {
  depends_on      = [aws_ec2_fleet.k3s_server]
  create_duration = "60s"
}

# Data source to get the server instance details
# Note: In LocalStack, fleet-id tag is not set, so we use Name tag as fallback
data "aws_instances" "k3s_server" {
  filter {
    name   = var.localstack_test == "yes" ? "tag:Name" : "tag:aws:ec2:fleet-id"
    values = var.localstack_test == "yes" ? ["hl-k3s-server"] : [aws_ec2_fleet.k3s_server.id]
  }

  filter {
    name   = "instance-state-name"
    values = ["running", "pending"]
  }

  depends_on = [time_sleep.wait_server_fleet]
}

# EC2 Fleet for k3s agent (single spot instance)
# See server fleet note above — same 2 GiB floor applies.
resource "aws_ec2_fleet" "k3s_agent" {
  launch_template_config {
    launch_template_specification {
      launch_template_id = aws_launch_template.k3s_agent.id
      version            = "$Latest"
    }
    override {
      instance_type = "t3.small"
    }
    override {
      instance_type = "t3a.small"
    }
    override {
      instance_type = "t3.medium"
    }
  }

  target_capacity_specification {
    default_target_capacity_type = "spot"
    total_target_capacity        = 1
    spot_target_capacity         = 1
  }

  spot_options {
    allocation_strategy            = "price-capacity-optimized"
    instance_interruption_behavior = "stop"
  }

  terminate_instances                 = true
  terminate_instances_with_expiration = false
  type                                = "maintain"

  # See postmortem note above (k3s_server fleet).
  lifecycle {
    ignore_changes = [spot_options[0].instance_pools_to_use_count]
  }

  tags = {
    Name = "hl-k3s-agent-fleet"
  }

  depends_on = [aws_ec2_fleet.k3s_server]
}

resource "time_sleep" "wait_agent_fleet" {
  depends_on      = [aws_ec2_fleet.k3s_agent]
  create_duration = "60s"
}

# Data source to get agent instance details
# Note: In LocalStack, fleet-id tag is not set, so we use Name tag as fallback
data "aws_instances" "k3s_agent" {
  filter {
    name   = var.localstack_test == "yes" ? "tag:Name" : "tag:aws:ec2:fleet-id"
    values = var.localstack_test == "yes" ? ["hl-k3s-agent"] : [aws_ec2_fleet.k3s_agent.id]
  }

  filter {
    name   = "instance-state-name"
    values = ["running", "pending"]
  }

  depends_on = [time_sleep.wait_agent_fleet]
}
