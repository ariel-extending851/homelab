# ==============================================================================
# EBS Snapshot Lifecycle Module (Data Lifecycle Manager)
# ==============================================================================
# Automated daily snapshots of the k3s EBS volumes with bounded retention.
# DLM itself is free; only snapshot storage is billed (~$0.05/GB-month,
# incremental). Volumes are selected by the `Snapshot = <tag value>` tag set on
# the launch-template volume tag_specifications in modules/compute.
#
# Why this exists: "snapshot drift" is a documented cost surprise
# (docs/operations/cost-and-scheduling.md) and there was no automated snapshot
# of the gp3 root volumes — a node loss meant rebuilding from scratch. DLM gives
# a cheap point-in-time fallback without touching the no-destroy-and-recreate
# recovery discipline.
# ==============================================================================

# DLM needs a service role it can assume to create/delete snapshots and tags.
resource "aws_iam_role" "dlm" {
  name_prefix          = "hl-dlm-lifecycle-"
  permissions_boundary = var.principal_boundary_arn # required on every hl- IAM role

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "dlm.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "hl-dlm-lifecycle-role"
  }
}

# AWS-managed policy scoped to exactly the snapshot lifecycle actions DLM needs
# (CreateSnapshot, CreateTags, DeleteSnapshot, Describe*). Not in the apply
# role's admin-attach denylist, so it attaches cleanly under the boundary.
resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "ebs" {
  description        = "Daily snapshots of k3s EBS volumes tagged ${var.snapshot_target_tag_value}"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    target_tags = {
      Snapshot = var.snapshot_target_tag_value
    }

    schedule {
      name = "Daily snapshots"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["03:00"] # UTC — outside the 10:00-21:00 BRT active window
      }

      retain_rule {
        count = var.snapshot_retain_count
      }

      copy_tags = true

      tags_to_add = {
        SnapshotCreator = "DLM"
        Name            = "hl-k3s-dlm-snapshot"
      }
    }
  }

  tags = {
    Name = "hl-k3s-ebs-snapshots"
  }
}
