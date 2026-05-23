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
# hop_limit raised from 1 → 2 to allow the Alloy DaemonSet pod (k8s/apps/alloy/)
# to reach IMDSv2 for its IAM instance profile. 2 is the AWS-recommended ceiling
# for pod-level workloads — it still blocks SSRF-from-host attacks but adds one
# hop for the CNI bridge. Must not exceed 2.

run "imds_hardened" {
  assert {
    condition     = aws_launch_template.k3s_server.metadata_options[0].http_tokens == "required"
    error_message = "Server launch template must enforce IMDSv2 (http_tokens=required)"
  }
  assert {
    condition     = aws_launch_template.k3s_server.metadata_options[0].http_put_response_hop_limit == 2
    error_message = "Server launch template hop_limit must be exactly 2 (pod IMDSv2 access + SSRF guard)"
  }
  assert {
    condition     = aws_launch_template.k3s_agent.metadata_options[0].http_tokens == "required"
    error_message = "Agent launch template must enforce IMDSv2 (http_tokens=required)"
  }
  assert {
    condition     = aws_launch_template.k3s_agent.metadata_options[0].http_put_response_hop_limit == 2
    error_message = "Agent launch template hop_limit must be exactly 2 (pod IMDSv2 access + SSRF guard)"
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

# ── Observability S3 policy (Alloy cold-storage write) ───────────────────────
# Asserts the policy exists when observability_bucket_arn is wired through, is
# scoped to the bucket ARN passed in, and stays write-only (no GetObject, no
# DeleteObject — cold reads happen out-of-band with a separate read-only role).

run "alloy_s3_policy_present_when_bucket_arn_set" {
  variables {
    observability_bucket_arn = "arn:aws:s3:::hl-observability-cold-storage-test"
  }
  assert {
    condition     = length(aws_iam_role_policy.k3s_node_observability_s3) == 1
    error_message = "Alloy S3 policy must be created when observability_bucket_arn is non-empty"
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.k3s_node_observability_s3[0].policy).Statement[0].Sid == "AlloyColdStorageWrite"
    error_message = "Alloy S3 policy statement Sid must be AlloyColdStorageWrite"
  }
  assert {
    condition     = contains(jsondecode(aws_iam_role_policy.k3s_node_observability_s3[0].policy).Statement[0].Action, "s3:PutObject")
    error_message = "Alloy S3 policy must allow s3:PutObject"
  }
  assert {
    condition     = !contains(jsondecode(aws_iam_role_policy.k3s_node_observability_s3[0].policy).Statement[0].Action, "s3:GetObject")
    error_message = "Alloy S3 policy must be write-only — no s3:GetObject"
  }
  assert {
    condition     = !contains(jsondecode(aws_iam_role_policy.k3s_node_observability_s3[0].policy).Statement[0].Action, "s3:DeleteObject")
    error_message = "Alloy S3 policy must be write-only — no s3:DeleteObject"
  }
}

run "alloy_s3_policy_absent_when_bucket_arn_empty" {
  assert {
    condition     = length(aws_iam_role_policy.k3s_node_observability_s3) == 0
    error_message = "Alloy S3 policy must be skipped when observability_bucket_arn is empty (LocalStack mode)"
  }
}
