# Tests for resource naming conventions in the compute module.
# Verifies all hl-* name prefixes and tags are consistent.

mock_provider "aws" {}

variables {
  server_instance_type = "t3.micro"
  agent_instance_type  = "t3.micro"
  ebs_volume_size      = 30
  spot_max_price       = ""
  ssh_key_name         = "test-key"
  ssh_public_key       = "ssh-ed25519 AAAA test"
  security_group_id    = "sg-test12345678"
  k3s_token            = "test-token"
  k3s_version          = "v1.31.0+k3s1"
  tailscale_auth_key   = "tskey-auth-test"
  ssm_s3_bucket        = "test-ssm-bucket"
  localstack_test      = "yes"
}

# ── IAM role ──────────────────────────────────────────────────────────────────

run "iam_role_naming" {
  assert {
    condition     = aws_iam_role.k3s_node.name_prefix == "hl-k3s-node-"
    error_message = "IAM role must have name_prefix 'hl-k3s-node-'"
  }
  assert {
    condition     = aws_iam_role.k3s_node.tags["Name"] == "hl-k3s-node-role"
    error_message = "IAM role must be tagged Name=hl-k3s-node-role"
  }
}

# ── Instance profile ──────────────────────────────────────────────────────────

run "instance_profile_naming" {
  assert {
    condition     = aws_iam_instance_profile.k3s_node.name_prefix == "hl-k3s-node-"
    error_message = "Instance profile must have name_prefix 'hl-k3s-node-'"
  }
  assert {
    condition     = aws_iam_instance_profile.k3s_node.tags["Name"] == "hl-k3s-node-profile"
    error_message = "Instance profile must be tagged Name=hl-k3s-node-profile"
  }
}

# ── Launch templates ──────────────────────────────────────────────────────────

run "launch_template_naming" {
  assert {
    condition     = aws_launch_template.k3s_server.name_prefix == "hl-k3s-server-"
    error_message = "Server launch template must have name_prefix 'hl-k3s-server-'"
  }
  assert {
    condition     = aws_launch_template.k3s_agent.name_prefix == "hl-k3s-agent-"
    error_message = "Agent launch template must have name_prefix 'hl-k3s-agent-'"
  }
  assert {
    condition     = aws_launch_template.k3s_server.tags["Name"] == "hl-k3s-server-launch-template"
    error_message = "Server launch template must be tagged Name=hl-k3s-server-launch-template"
  }
  assert {
    condition     = aws_launch_template.k3s_agent.tags["Name"] == "hl-k3s-agent-launch-template"
    error_message = "Agent launch template must be tagged Name=hl-k3s-agent-launch-template"
  }
}

# ── EC2 Fleets ────────────────────────────────────────────────────────────────

run "fleet_naming" {
  assert {
    condition     = aws_ec2_fleet.k3s_server.tags["Name"] == "hl-k3s-server-fleet"
    error_message = "Server fleet must be tagged Name=hl-k3s-server-fleet"
  }
  assert {
    condition     = aws_ec2_fleet.k3s_agent.tags["Name"] == "hl-k3s-agent-fleet"
    error_message = "Agent fleet must be tagged Name=hl-k3s-agent-fleet"
  }
}
