# Tests for security hardening properties of compute resources.
# Verifies IMDSv2, EBS encryption, and IAM least-privilege configuration.

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

# ── IMDSv2 enforcement ────────────────────────────────────────────────────────

run "imds_hardened" {
  assert {
    condition     = aws_launch_template.k3s_server.metadata_options[0].http_tokens == "required"
    error_message = "Server launch template must enforce IMDSv2 (http_tokens=required)"
  }
  assert {
    condition     = aws_launch_template.k3s_server.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "Server launch template must set hop_limit=1 to prevent SSRF to IMDS"
  }
  assert {
    condition     = aws_launch_template.k3s_agent.metadata_options[0].http_tokens == "required"
    error_message = "Agent launch template must enforce IMDSv2 (http_tokens=required)"
  }
  assert {
    condition     = aws_launch_template.k3s_agent.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "Agent launch template must set hop_limit=1 to prevent SSRF to IMDS"
  }
}

# ── EBS encryption ────────────────────────────────────────────────────────────

run "ebs_encrypted" {
  assert {
      condition     = try(aws_launch_template.k3s_server.block_device_mappings[0].ebs[0].encrypted, false) == true || try(aws_launch_template.k3s_server.block_device_mappings[0].ebs[0].encrypted, false) == "true"
    error_message = "Server EBS volume must be encrypted at rest"
  }
  assert {
    condition     = aws_launch_template.k3s_server.block_device_mappings[0].ebs[0].volume_type == "gp3"
    error_message = "Server EBS volume must use gp3 for cost/performance"
  }
  assert {
      condition     = try(aws_launch_template.k3s_agent.block_device_mappings[0].ebs[0].encrypted, false) == true || try(aws_launch_template.k3s_agent.block_device_mappings[0].ebs[0].encrypted, false) == "true"
    error_message = "Agent EBS volume must be encrypted at rest"
  }
  assert {
    condition     = aws_launch_template.k3s_agent.block_device_mappings[0].ebs[0].volume_type == "gp3"
    error_message = "Agent EBS volume must use gp3 for cost/performance"
  }
}

# ── SSM policy ────────────────────────────────────────────────────────────────

run "ssm_policy_attached" {
  assert {
    condition     = aws_iam_role_policy_attachment.k3s_node_ssm.policy_arn == "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    error_message = "SSM policy attachment must use AmazonSSMManagedInstanceCore"
  }
}

# ── S3 least-privilege ────────────────────────────────────────────────────────

run "s3_policy_least_privilege" {
  assert {
    condition     = jsondecode(aws_iam_role_policy.k3s_node_ssm_s3.policy).Statement[0].Sid == "SSMFileTransfer"
    error_message = "S3 policy statement must be Sid=SSMFileTransfer"
  }
  assert {
    condition     = contains(jsondecode(aws_iam_role_policy.k3s_node_ssm_s3.policy).Statement[0].Action, "s3:GetObject")
    error_message = "S3 policy must include s3:GetObject for SSM file transfer"
  }
  assert {
    condition     = contains(jsondecode(aws_iam_role_policy.k3s_node_ssm_s3.policy).Statement[0].Action, "s3:PutObject")
    error_message = "S3 policy must include s3:PutObject for SSM file transfer"
  }
  assert {
    condition     = length(jsondecode(aws_iam_role_policy.k3s_node_ssm_s3.policy).Statement[0].Action) == 2
    error_message = "S3 policy must have exactly 2 actions (GetObject, PutObject) — ListBucket removed to reduce attack surface"
  }
}
