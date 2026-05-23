# Tests for the observability module — asserts cold-storage tiering,
# encryption-at-rest, and the bucket policy that hardens against insecure
# and unencrypted writes.

mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

# ── Bucket hardening ─────────────────────────────────────────────────────────

run "bucket_name_uses_hl_prefix" {
  assert {
    condition     = startswith(aws_s3_bucket.cold_storage.bucket_prefix, "hl-")
    error_message = "Bucket prefix must use the hl- naming convention (docs/CONVENTIONS.md)."
  }
}

run "bucket_blocks_public_access" {
  assert {
    condition = (
      aws_s3_bucket_public_access_block.cold_storage.block_public_acls &&
      aws_s3_bucket_public_access_block.cold_storage.block_public_policy &&
      aws_s3_bucket_public_access_block.cold_storage.ignore_public_acls &&
      aws_s3_bucket_public_access_block.cold_storage.restrict_public_buckets
    )
    error_message = "All four public-access-block flags must be true."
  }
}

run "bucket_force_destroy_disabled" {
  assert {
    condition     = aws_s3_bucket.cold_storage.force_destroy == false
    error_message = "Cold-storage bucket must not allow force_destroy — archived logs are evidentiary."
  }
}

run "bucket_is_versioned" {
  assert {
    condition     = aws_s3_bucket_versioning.cold_storage.versioning_configuration[0].status == "Enabled"
    error_message = "Bucket must be versioned to survive accidental overwrite from a misbehaving Alloy instance."
  }
}

run "bucket_is_encrypted" {
  assert {
    condition     = one(aws_s3_bucket_server_side_encryption_configuration.cold_storage.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "AES256"
    error_message = "Bucket must enforce SSE-S3 encryption-at-rest."
  }
}

# ── Lifecycle: must tier to Deep Archive ─────────────────────────────────────

run "lifecycle_transitions_to_standard_ia" {
  assert {
    condition = anytrue([
      for t in one(aws_s3_bucket_lifecycle_configuration.cold_storage.rule).transition :
      t.storage_class == "STANDARD_IA"
    ])
    error_message = "Lifecycle must transition to STANDARD_IA at 30 days."
  }
}

run "lifecycle_transitions_to_deep_archive" {
  assert {
    condition = anytrue([
      for t in one(aws_s3_bucket_lifecycle_configuration.cold_storage.rule).transition :
      t.storage_class == "DEEP_ARCHIVE"
    ])
    error_message = "Lifecycle must transition to DEEP_ARCHIVE for long-term cost compression."
  }
}

run "lifecycle_aborts_incomplete_multipart" {
  assert {
    condition     = one(aws_s3_bucket_lifecycle_configuration.cold_storage.rule).abort_incomplete_multipart_upload[0].days_after_initiation == 7
    error_message = "Incomplete multipart uploads must be aborted at 7 days to prevent leaked storage charges."
  }
}

# ── Variable validations ─────────────────────────────────────────────────────

run "rejects_non_hl_prefix" {
  command = plan
  variables {
    bucket_name_prefix = "homelab-bad-"
  }
  expect_failures = [var.bucket_name_prefix]
}

run "rejects_short_retention" {
  command = plan
  variables {
    retention_days = 30
  }
  expect_failures = [var.retention_days]
}

run "rejects_ia_below_30_days" {
  command = plan
  variables {
    lifecycle_ia_days = 7
  }
  expect_failures = [var.lifecycle_ia_days]
}
