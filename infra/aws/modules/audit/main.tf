# ==============================================================================
# AWS Audit Module — CloudTrail + GuardDuty (cost-bounded)
# ==============================================================================
# Provides forensic trail and threat detection for the homelab account.
#
# Cost envelope (target <$5/month):
#   - CloudTrail: management events only on a single trail (free; AWS does
#     not charge for the first management trail). Multi-region disabled,
#     data events disabled (these are the expensive options).
#   - S3 storage: Standard → IA after 30d → Glacier after 90d → expire 365d.
#   - GuardDuty: single regional detector, default 6h finding-publishing
#     frequency. After the 30-day free trial, expect $0.50–$2/month at
#     homelab volume.
#
# Out of scope (deliberately, by cost): AWS Config, Security Hub, Macie,
# multi-region trails, S3 data events, EventBridge fan-out.
# ==============================================================================

data "aws_caller_identity" "current" {}

# ── CloudTrail S3 bucket ─────────────────────────────────────────────────────

# tfsec:ignore:aws-s3-enable-bucket-logging
resource "aws_s3_bucket" "trail" {
  bucket        = var.trail_bucket_name
  force_destroy = false # audit logs are evidentiary — opt-out of accidental deletion

  tags = {
    Name    = var.trail_bucket_name
    Purpose = "CloudTrail audit logs"
  }
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket = aws_s3_bucket.trail.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# tfsec:ignore:aws-s3-encryption-customer-key
resource "aws_s3_bucket_server_side_encryption_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "trail" {
  bucket = aws_s3_bucket.trail.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "trail" {
  bucket = aws_s3_bucket.trail.id

  rule {
    id     = "tier-and-expire-trail-logs"
    status = "Enabled"

    filter {}

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = var.trail_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# CloudTrail requires a bucket policy granting it write access.
data "aws_iam_policy_document" "trail_bucket" {
  statement {
    sid     = "AWSCloudTrailAclCheck"
    actions = ["s3:GetBucketAcl"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    resources = [aws_s3_bucket.trail.arn]
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${var.trail_name}"]
    }
  }

  statement {
    sid     = "AWSCloudTrailWrite"
    actions = ["s3:PutObject"]
    principals {
      type        = "Service"
      identifiers = ["cloudtrail.amazonaws.com"]
    }
    resources = ["${aws_s3_bucket.trail.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    condition {
      test     = "StringEquals"
      variable = "s3:x-amz-acl"
      values   = ["bucket-owner-full-control"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceArn"
      values   = ["arn:aws:cloudtrail:${var.aws_region}:${data.aws_caller_identity.current.account_id}:trail/${var.trail_name}"]
    }
  }
}

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id
  policy = data.aws_iam_policy_document.trail_bucket.json
}

# ── CloudTrail (management events only, single-region) ───────────────────────

resource "aws_cloudtrail" "main" {
  name           = var.trail_name
  s3_bucket_name = aws_s3_bucket.trail.id

  # Cost guards: management events only (free), single region.
  is_multi_region_trail         = false
  include_global_service_events = true
  enable_log_file_validation    = true

  # No event_selector blocks: that means default = log management events,
  # no data events. Data events on S3/Lambda are the expensive option and
  # are explicitly omitted to stay under the $5/month envelope.

  depends_on = [aws_s3_bucket_policy.trail]

  tags = {
    Name = var.trail_name
  }
}

# ── GuardDuty (single-region detector, default frequency) ────────────────────

resource "aws_guardduty_detector" "main" {
  enable                       = true
  finding_publishing_frequency = "SIX_HOURS" # cheapest cadence

  tags = {
    Name = "homelab-guardduty"
  }
}
