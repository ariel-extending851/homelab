# ==============================================================================
# Audit Module Variables
# ==============================================================================

variable "aws_region" {
  description = "AWS region for the trail. Single-region by design (cost guard)."
  type        = string
  default     = "us-east-1"
}

variable "trail_name" {
  description = "Name of the CloudTrail trail."
  type        = string
  default     = "homelab-audit"
}

variable "trail_bucket_name" {
  description = "S3 bucket name for CloudTrail logs. Must be globally unique."
  type        = string

  validation {
    condition     = length(var.trail_bucket_name) >= 3 && length(var.trail_bucket_name) <= 63
    error_message = "S3 bucket names must be 3-63 characters."
  }
}

variable "trail_retention_days" {
  description = "Days to retain CloudTrail logs in S3 before expiration. Lifecycle moves to IA at 30d, Glacier at 90d."
  type        = number
  default     = 365

  validation {
    condition     = var.trail_retention_days >= 90 && var.trail_retention_days <= 2555
    error_message = "Retention must be 90-2555 days (compliance min/max)."
  }
}
