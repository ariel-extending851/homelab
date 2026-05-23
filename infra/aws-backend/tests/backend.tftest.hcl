# Tests for the S3+DynamoDB remote state backend module.

mock_provider "aws" {}
mock_provider "random" {}

# ── S3 bucket naming ──────────────────────────────────────────────────────────

run "s3_bucket_name_has_homelab_prefix" {
  assert {
    condition     = startswith(aws_s3_bucket.terraform_state.bucket, "homelab-terraform-state-")
    error_message = "State bucket name must start with 'homelab-terraform-state-'"
  }
}

# ── encryption enabled ────────────────────────────────────────────────────────

run "s3_encryption_uses_aes256" {
  assert {
    condition = contains(
      flatten([
        for rule in aws_s3_bucket_server_side_encryption_configuration.state_encryption.rule : [
          for enc in rule.apply_server_side_encryption_by_default : enc.sse_algorithm
        ]
      ]),
      "AES256"
    )
    error_message = "State bucket must use AES256 server-side encryption"
  }
}

# ── versioning enabled ────────────────────────────────────────────────────────

run "s3_versioning_enabled" {
  assert {
    condition     = aws_s3_bucket_versioning.state_versioning.versioning_configuration[0].status == "Enabled"
    error_message = "State bucket must have versioning enabled"
  }
}

# ── public access blocked ─────────────────────────────────────────────────────

run "s3_public_access_fully_blocked" {
  assert {
    condition = (
      aws_s3_bucket_public_access_block.state_public_access.block_public_acls == true &&
      aws_s3_bucket_public_access_block.state_public_access.block_public_policy == true &&
      aws_s3_bucket_public_access_block.state_public_access.ignore_public_acls == true &&
      aws_s3_bucket_public_access_block.state_public_access.restrict_public_buckets == true
    )
    error_message = "All four public access block settings must be true on the state bucket"
  }
}

# ── DynamoDB locking table ────────────────────────────────────────────────────

run "dynamodb_table_naming" {
  assert {
    condition     = aws_dynamodb_table.terraform_state_lock.name == "homelab-terraform-state-lock"
    error_message = "DynamoDB lock table must be named 'homelab-terraform-state-lock'"
  }
  assert {
    condition     = aws_dynamodb_table.terraform_state_lock.billing_mode == "PAY_PER_REQUEST"
    error_message = "DynamoDB table must use PAY_PER_REQUEST billing for cost optimization"
  }
}
