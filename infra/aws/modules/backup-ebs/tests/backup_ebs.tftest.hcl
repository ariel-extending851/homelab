# Tests for the backup-ebs (DLM) module. Mocked AWS provider — no real API calls.

mock_provider "aws" {}

run "dlm_targets_snapshot_tag_with_boundary" {
  variables {
    snapshot_retain_count  = 7
    principal_boundary_arn = "arn:aws:iam::123456789012:policy/homelab-principal-boundary"
  }
  command = plan

  assert {
    condition     = aws_dlm_lifecycle_policy.ebs.policy_details[0].target_tags["Snapshot"] == "hl-k3s"
    error_message = "DLM must target volumes by Snapshot=hl-k3s (the tag set in the compute module)."
  }

  assert {
    condition     = aws_iam_role.dlm.permissions_boundary == "arn:aws:iam::123456789012:policy/homelab-principal-boundary"
    error_message = "The DLM service role must carry the homelab principal boundary."
  }
}

run "retain_count_zero_rejected" {
  variables {
    snapshot_retain_count = 0
  }
  command         = plan
  expect_failures = [var.snapshot_retain_count]
}

run "retain_count_above_max_rejected" {
  variables {
    snapshot_retain_count = 15
  }
  command         = plan
  expect_failures = [var.snapshot_retain_count]
}
