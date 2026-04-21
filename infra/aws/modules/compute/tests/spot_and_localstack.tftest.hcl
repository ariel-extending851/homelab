# Tests for EC2 Spot fleet configuration and LocalStack conditional logic.
# Verifies spot strategy, interruption behavior, and key pair count gating.

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

# ── Spot fleet cost-optimization config ───────────────────────────────────────

run "spot_fleet_config" {
  assert {
    condition     = aws_ec2_fleet.k3s_server.spot_options[0].allocation_strategy == "price-capacity-optimized"
    error_message = "Server fleet must use price-capacity-optimized spot strategy"
  }
  assert {
    condition     = aws_ec2_fleet.k3s_server.spot_options[0].instance_interruption_behavior == "stop"
    error_message = "Server fleet must stop (not terminate) on spot interruption to preserve EBS data"
  }
  assert {
    condition     = aws_ec2_fleet.k3s_server.type == "maintain"
    error_message = "Server fleet type must be 'maintain' for persistent capacity"
  }
  assert {
    condition     = aws_ec2_fleet.k3s_agent.spot_options[0].allocation_strategy == "price-capacity-optimized"
    error_message = "Agent fleet must use price-capacity-optimized spot strategy"
  }
  assert {
    condition     = aws_ec2_fleet.k3s_agent.spot_options[0].instance_interruption_behavior == "stop"
    error_message = "Agent fleet must stop on spot interruption"
  }
  assert {
    condition     = aws_ec2_fleet.k3s_agent.type == "maintain"
    error_message = "Agent fleet type must be 'maintain'"
  }
}

# ── LocalStack skips SSH key pair creation ────────────────────────────────────

run "localstack_no_key_pair" {
  variables {
    localstack_test = "yes"
  }
  assert {
    condition     = length(aws_key_pair.homelab) == 0
    error_message = "LocalStack mode must skip key pair creation (count=0)"
  }
}

# ── Production creates SSH key pair ──────────────────────────────────────────

run "prod_has_key_pair" {
  variables {
    localstack_test = "no"
  }
  assert {
    condition     = length(aws_key_pair.homelab) == 1
    error_message = "Production mode must create exactly 1 key pair (count=1)"
  }
  assert {
    condition     = aws_key_pair.homelab[0].tags["Name"] == "hl-homelab-key"
    error_message = "Key pair must be tagged Name=hl-homelab-key"
  }
}
