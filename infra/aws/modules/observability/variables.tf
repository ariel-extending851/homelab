# ==============================================================================
# Observability Module Variables
# ==============================================================================

variable "bucket_name_prefix" {
  description = "Prefix for the S3 bucket name. AWS appends a random suffix to keep the name globally unique."
  type        = string
  default     = "hl-observability-cold-storage-"

  validation {
    condition     = can(regex("^hl-[a-z0-9-]+-$", var.bucket_name_prefix))
    error_message = "Bucket name prefix must start with 'hl-', be lowercase kebab-case, and end with a trailing hyphen."
  }
}

variable "lifecycle_ia_days" {
  description = "Days before transitioning objects from Standard to Standard-IA. Cost-tiering knob."
  type        = number
  default     = 30

  validation {
    condition     = var.lifecycle_ia_days >= 30 && var.lifecycle_ia_days <= 90
    error_message = "Standard-IA transition must be 30-90 days (S3 minimum 30, beyond 90 defeats the tier)."
  }
}

variable "lifecycle_glacier_days" {
  description = "Days before transitioning objects from Standard-IA to Deep Archive."
  type        = number
  default     = 90

  validation {
    condition     = var.lifecycle_glacier_days >= 60 && var.lifecycle_glacier_days <= 365
    error_message = "Deep Archive transition must be 60-365 days."
  }
}

variable "retention_days" {
  description = "Days to retain objects before expiration. Compliance / FinOps knob."
  type        = number
  default     = 730

  validation {
    condition     = var.retention_days >= 90 && var.retention_days <= 2555
    error_message = "Retention must be 90-2555 days (compliance min, S3 maximum sane value)."
  }
}
