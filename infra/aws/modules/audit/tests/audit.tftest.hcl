# Tests for the audit module — asserts cost-guard configuration and that
# the CloudTrail S3 bucket is hardened (private, encrypted, versioned,
# lifecycle-tiered).

mock_provider "aws" {
  # The bucket policy resource validates the JSON it receives, so the mocked
  # data source must return a real (if minimal) JSON document.
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
      arn        = "arn:aws:iam::123456789012:user/test"
      user_id    = "AIDAEXAMPLE"
    }
  }
}

variables {
  trail_bucket_name = "homelab-audit-test-bucket"
}

# ── Cost guards: trail must stay single-region, management-events only ───────

run "trail_is_single_region" {
  assert {
    condition     = aws_cloudtrail.main.is_multi_region_trail == false
    error_message = "Trail must be single-region (cost guard — multi-region is billed per region)."
  }
}

run "trail_has_no_data_events" {
  assert {
    condition     = length(aws_cloudtrail.main.event_selector) == 0
    error_message = "Trail must not declare event_selector blocks (default = management-only, the free tier)."
  }
}

run "trail_log_validation_enabled" {
  assert {
    condition     = aws_cloudtrail.main.enable_log_file_validation == true
    error_message = "Log file validation must be enabled for forensic integrity."
  }
}

# ── S3 bucket hardening ──────────────────────────────────────────────────────

run "s3_bucket_blocks_public_access" {
  assert {
    condition = (
      aws_s3_bucket_public_access_block.trail.block_public_acls &&
      aws_s3_bucket_public_access_block.trail.block_public_policy &&
      aws_s3_bucket_public_access_block.trail.ignore_public_acls &&
      aws_s3_bucket_public_access_block.trail.restrict_public_buckets
    )
    error_message = "All four public-access-block flags must be true."
  }
}

run "s3_bucket_is_versioned" {
  assert {
    condition     = aws_s3_bucket_versioning.trail.versioning_configuration[0].status == "Enabled"
    error_message = "Bucket must be versioned (forensic recovery)."
  }
}

run "s3_bucket_is_encrypted" {
  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.trail.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "Bucket must enforce server-side encryption."
  }
}

run "s3_bucket_lifecycle_tiers_to_glacier" {
  assert {
    condition = anytrue([
      for t in one(aws_s3_bucket_lifecycle_configuration.trail.rule).transition :
      t.storage_class == "GLACIER"
    ])
    error_message = "Lifecycle must transition to GLACIER (90d) to keep storage cost flat."
  }
}

run "s3_bucket_force_destroy_disabled" {
  assert {
    condition     = aws_s3_bucket.trail.force_destroy == false
    error_message = "Audit bucket must not allow force_destroy — logs are evidentiary."
  }
}

# ── GuardDuty: cheapest cadence ──────────────────────────────────────────────

run "guardduty_uses_cheapest_publishing_frequency" {
  assert {
    condition     = aws_guardduty_detector.main.finding_publishing_frequency == "SIX_HOURS"
    error_message = "GuardDuty publishing frequency must be SIX_HOURS (cheapest cadence)."
  }
  assert {
    condition     = aws_guardduty_detector.main.enable == true
    error_message = "GuardDuty detector must be enabled."
  }
}

# ── Variable validations ─────────────────────────────────────────────────────

run "rejects_short_retention" {
  command = plan
  variables {
    trail_bucket_name    = "homelab-audit-test-bucket"
    trail_retention_days = 30
  }
  expect_failures = [var.trail_retention_days]
}
