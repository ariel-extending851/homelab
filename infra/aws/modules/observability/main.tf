# ==============================================================================
# AWS Observability Module — Cold-Storage S3 Bucket for Alloy Log Archive
# ==============================================================================
# Receives gzipped OTLP-proto batches from the Grafana Alloy DaemonSet
# (otelcol.exporter.awss3) for long-term retention beyond the 14-day
# Grafana Cloud Loki hot window. Companion to the Alloy stack defined in
# k8s/apps/alloy/ and ansible/roles/alloy/.
#
# Cost envelope (target <$3/month at homelab volume):
#   - 5-minute batched, gzip-compressed objects keyed by minute-partition
#   - Standard → Standard-IA after 30 days → Deep Archive after 90 days
#   - Expire after 730 days (configurable)
#   - Abort incomplete multipart uploads after 7 days
#   - Bucket policy denies non-TLS PUT and unencrypted PUT
#
# Writes only — the EC2 IAM role gets PutObject / multipart actions only.
# No GetObject, no DeleteObject. Cold reads happen out-of-band (operator from
# a Tailscale node with a separate read-only IAM principal, future work).
# ==============================================================================

# tfsec:ignore:aws-s3-enable-bucket-logging — homelab cost envelope; access
# pattern is write-only-by-IAM, no need for access logging at this scale.
resource "aws_s3_bucket" "cold_storage" {
  bucket_prefix = var.bucket_name_prefix
  force_destroy = false # logs are evidentiary; opt-out of accidental deletion

  tags = {
    # AWS S3 tag values charset is restricted to letters, digits, spaces,
    # and _.:/=+-@. The original `${prefix}*` (wildcard) and the `()`
    # parens in Purpose both violated the rule and produced InvalidTag
    # on PutBucketTagging.
    Name    = var.bucket_name_prefix
    Purpose = "Alloy cold-storage log archive via otelcol.exporter.awss3"
  }
}

resource "aws_s3_bucket_public_access_block" "cold_storage" {
  bucket = aws_s3_bucket.cold_storage.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# tfsec:ignore:aws-s3-encryption-customer-key — SSE-S3 is the cost-bounded
# choice for homelab; KMS adds per-request charges that scale with PUT volume.
resource "aws_s3_bucket_server_side_encryption_configuration" "cold_storage" {
  bucket = aws_s3_bucket.cold_storage.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "cold_storage" {
  bucket = aws_s3_bucket.cold_storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cold_storage" {
  bucket = aws_s3_bucket.cold_storage.id

  rule {
    id     = "cold-tiering"
    status = "Enabled"

    filter {}

    # 5-minute batched objects are too small for INTELLIGENT_TIERING to pay
    # off (objects under 128 KB get the same rate as Standard). Plain stepped
    # tiering wins on simplicity and predictability at homelab volume.
    transition {
      days          = var.lifecycle_ia_days
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = var.lifecycle_glacier_days
      storage_class = "DEEP_ARCHIVE"
    }

    expiration {
      days = var.retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    # Abort multipart uploads stuck in the bucket — Alloy's S3 exporter uses
    # multipart for batches > 5 MiB and a daemon crash mid-upload would
    # otherwise leak storage charges indefinitely.
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Bucket policy: belt-and-braces denial of insecure writes. The IAM role on
# the EC2 instance is already write-only, but a misconfigured client (or a
# future read role) cannot bypass TLS because the bucket rejects the
# request at S3-edge before AWS evaluates the IAM policy.
#
# Note on encryption: the original PR shipped a `DenyUnencryptedPut`
# statement that required the `s3:x-amz-server-side-encryption=AES256`
# request header. Alloy's `otelcol.exporter.awss3` (v1.5.1) does not send
# that header, so the deny triggered on every PUT (403 AccessDenied) and
# the cold-storage pipeline never worked. Default encryption is enforced
# by `aws_s3_bucket_server_side_encryption_configuration.cold_storage`
# above — objects land AES256 regardless of header. The deny statement
# was dropped because it duplicated the at-rest control while breaking
# the only client.
data "aws_iam_policy_document" "cold_storage" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    resources = [
      aws_s3_bucket.cold_storage.arn,
      "${aws_s3_bucket.cold_storage.arn}/*",
    ]
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "cold_storage" {
  bucket = aws_s3_bucket.cold_storage.id
  policy = data.aws_iam_policy_document.cold_storage.json
}
