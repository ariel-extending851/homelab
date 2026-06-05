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
  name_prefix          = "hl-k3s-node-"
  permissions_boundary = var.principal_boundary_arn

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

# Inline S3 policy — allows the Alloy DaemonSet to archive logs to the
# cold-storage bucket via the EC2 instance profile (IMDSv2). Write-only by
# design: no GetObject, no DeleteObject. Multipart actions are required
# because Alloy's awss3 exporter uses multipart for batches > 5 MiB.
#
# Gated on observability_bucket_arn being non-empty so the module is still
# applyable under LocalStack (where the observability module is skipped).
# count = 0 in that case; count = 1 in production.
resource "aws_iam_role_policy" "k3s_node_observability_s3" {
  count = var.observability_bucket_arn == "" ? 0 : 1

  name_prefix = "hl-alloy-s3-export-"
  role        = aws_iam_role.k3s_node.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AlloyColdStorageWrite"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:AbortMultipartUpload",
          "s3:ListBucketMultipartUploads",
        ]
        Resource = [
          var.observability_bucket_arn,
          "${var.observability_bucket_arn}/*",
        ]
      }
    ]
  })
}

# Inline ECR policy — lets the k3s_node role pull images from the private ECR
# repos (modules/ecr) so the cluster avoids Docker Hub anonymous rate limits.
# Read-only: GetAuthorizationToken (account-level, AWS mandates Resource "*")
# plus the three pull actions scoped to the homelab repo ARNs.
#
# Gated on ecr_repository_arns being non-empty so the module still applies
# under LocalStack (where the ECR module is skipped) — same idiom as the
# observability-S3 policy above.
resource "aws_iam_role_policy" "k3s_node_ecr_pull" {
  count = length(var.ecr_repository_arns) > 0 ? 1 : 0

  name_prefix = "hl-ecr-pull-"
  role        = aws_iam_role.k3s_node.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRAuthToken"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "ECRPullHomelabRepos"
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
        ]
        Resource = var.ecr_repository_arns
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
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only
    # hop_limit = 2 lets the Alloy DaemonSet pod reach IMDSv2 from inside the
    # pod network namespace (one extra hop for the CNI bridge). Stays at the
    # AWS-recommended ceiling for IMDS exposure — caps the blast radius if a
    # workload ever runs at the host level with hostNetwork: false.
    http_put_response_hop_limit = 2
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
      # Selector for the DLM snapshot policy (modules/backup-ebs). A single
      # stable tag value across both volumes lets one DLM policy target them.
      Snapshot = "hl-k3s"
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
    http_endpoint = "enabled"
    http_tokens   = "required" # IMDSv2 only
    # See server launch template above: hop_limit = 2 is the minimum for the
    # Alloy DaemonSet to reach IMDSv2 from the pod network namespace.
    http_put_response_hop_limit = 2
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
      # Selector for the DLM snapshot policy (modules/backup-ebs).
      Snapshot = "hl-k3s"
    }
  }

  tags = {
    Name = "hl-k3s-agent-launch-template"
  }
}

# EC2 Fleet for k3s server (single spot instance)
#
# Override list floors at 4 GiB RAM (t3.medium) — see project_prod_deploy_2026_05
# 2026-05-04 deploy postmortem (gotcha #16): spot fleet's price-capacity-optimized
# strategy picks the cheapest pool that has capacity, ignoring the launch
# template's instance_type. The earlier floor at 2 GiB (t3.small) let prod
# silently come up as t3.small, where the control plane (etcd + kube-apiserver
# + ArgoCD repo-server CMP sidecar) ran tight and the kustomize manifest
# generation pushed close to the 2 GiB ceiling — same shape as the recurring
# k3d CMP-sidecar startup race we see in CI. Pinning to t3.medium-class
# preserves Intel/AMD diversity for the allocation strategy.
#
# Agent fleet (below) keeps the wider override list — workers are kubelet +
# small DaemonSets and run comfortably at 2 GiB.
resource "aws_ec2_fleet" "k3s_server" {
  launch_template_config {
    launch_template_specification {
      launch_template_id = aws_launch_template.k3s_server.id
      version            = "$Latest"
    }
    override {
      instance_type = "t3.medium"
    }
    override {
      instance_type = "t3a.medium"
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
