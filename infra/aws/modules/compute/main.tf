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
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.k3s_node.name
  }

  key_name = var.localstack_test == "yes" ? null : aws_key_pair.homelab[0].key_name

  vpc_security_group_ids = [var.security_group_id]

  user_data = base64encode(templatefile("${path.module}/templates/user_data.tftpl", {
    k3s_token   = var.k3s_token
    k3s_version = var.k3s_version
    node_index  = 1
    node_type   = "server"
    server_ip   = "" # Not used for server node
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
# Note: Cannot reference server private IP here, must use data source after server is created
resource "aws_launch_template" "k3s_agent" {
  name_prefix   = "hl-k3s-agent-"
  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.k3s_node.name
  }

  key_name = var.localstack_test == "yes" ? null : aws_key_pair.homelab[0].key_name

  vpc_security_group_ids = [var.security_group_id]

  # Placeholder user_data - will be updated after server IP is known
  user_data = base64encode(templatefile("${path.module}/templates/user_data.tftpl", {
    k3s_token   = var.k3s_token
    k3s_version = var.k3s_version
    node_index  = 2
    node_type   = "agent"
    server_ip   = "SERVER_IP_PLACEHOLDER" # Will be updated via launch template version
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
resource "aws_ec2_fleet" "k3s_server" {
  launch_template_config {
    launch_template_specification {
      launch_template_id = aws_launch_template.k3s_server.id
      version            = "$Latest"
    }
  }

  target_capacity_specification {
    default_target_capacity_type = "spot"
    total_target_capacity        = 1
    spot_target_capacity         = 1
  }

  spot_options {
    allocation_strategy            = "price-capacity-optimized"
    instance_interruption_behavior = "terminate"
  }

  terminate_instances                 = true
  terminate_instances_with_expiration = false
  type                                = "maintain"

  tags = {
    Name = "hl-k3s-server-fleet"
  }
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

  depends_on = [aws_ec2_fleet.k3s_server]
}

# Update agent launch template with server IP
resource "aws_launch_template" "k3s_agent_final" {
  name_prefix   = "hl-k3s-agent-final-"
  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = var.instance_type

  iam_instance_profile {
    name = aws_iam_instance_profile.k3s_node.name
  }

  key_name = var.localstack_test == "yes" ? null : aws_key_pair.homelab[0].key_name

  vpc_security_group_ids = [var.security_group_id]

  user_data = base64encode(templatefile("${path.module}/templates/user_data.tftpl", {
    k3s_token   = var.k3s_token
    k3s_version = var.k3s_version
    node_index  = 2
    node_type   = "agent"
    server_ip   = length(data.aws_instances.k3s_server.private_ips) > 0 ? data.aws_instances.k3s_server.private_ips[0] : ""
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
    http_tokens                 = "required"
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
    Name = "hl-k3s-agent-launch-template-final"
  }

  depends_on = [data.aws_instances.k3s_server]
}

# EC2 Fleet for k3s agent (single spot instance)
resource "aws_ec2_fleet" "k3s_agent" {
  launch_template_config {
    launch_template_specification {
      launch_template_id = aws_launch_template.k3s_agent_final.id
      version            = "$Latest"
    }
  }

  target_capacity_specification {
    default_target_capacity_type = "spot"
    total_target_capacity        = 1
    spot_target_capacity         = 1
  }

  spot_options {
    allocation_strategy            = "price-capacity-optimized"
    instance_interruption_behavior = "terminate"
  }

  terminate_instances                 = true
  terminate_instances_with_expiration = false
  type                                = "maintain"

  tags = {
    Name = "hl-k3s-agent-fleet"
  }

  depends_on = [aws_ec2_fleet.k3s_server, data.aws_instances.k3s_server]
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

  depends_on = [aws_ec2_fleet.k3s_agent]
}
