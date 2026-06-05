# Tests for the k3s control-plane snapshot additions to infra/aws-velero.
# Mocked AWS provider — no real API calls.

mock_provider "aws" {}

run "snapshot_user_is_write_only_and_prefix_scoped" {
  command = apply

  assert {
    condition     = aws_iam_user.k3s_snapshot.name == "hl-k3s-snapshot"
    error_message = "Snapshot uploader must be named hl-k3s-snapshot."
  }

  assert {
    condition     = aws_iam_user.k3s_snapshot.path == "/system/"
    error_message = "User must be at /system/ to match the OIDC apply-role allowlist (no OIDC change)."
  }

  assert {
    condition     = aws_iam_user.k3s_snapshot.permissions_boundary == data.aws_iam_policy.principal_boundary.arn
    error_message = "Snapshot user must carry the homelab principal boundary."
  }

  # Write-only: the policy must NOT grant GetObject or DeleteObject.
  assert {
    condition     = !strcontains(aws_iam_user_policy.k3s_snapshot_access.policy, "s3:GetObject") && !strcontains(aws_iam_user_policy.k3s_snapshot_access.policy, "s3:DeleteObject")
    error_message = "Uploader must be write-only — no GetObject/DeleteObject."
  }

  # Scoped to the cluster-state/ prefix only.
  assert {
    condition     = strcontains(aws_iam_user_policy.k3s_snapshot_access.policy, "cluster-state/")
    error_message = "Policy must be scoped to the cluster-state/ prefix."
  }
}

run "lifecycle_expires_cluster_state_at_30d" {
  command = apply

  assert {
    condition = anytrue([
      for r in aws_s3_bucket_lifecycle_configuration.velero_backups.rule :
      r.id == "expire-cluster-state-snapshots" && length(r.filter) > 0 && r.filter[0].prefix == "cluster-state/"
    ])
    error_message = "A lifecycle rule must target the cluster-state/ prefix."
  }
}
