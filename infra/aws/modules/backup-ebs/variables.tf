# ==============================================================================
# EBS Snapshot Lifecycle Module Variables
# ==============================================================================

variable "snapshot_retain_count" {
  description = "Number of daily snapshots to retain per volume before DLM expires the oldest. Snapshots are incremental, so storage cost grows slowly."
  type        = number
  default     = 7

  validation {
    condition     = var.snapshot_retain_count >= 1 && var.snapshot_retain_count <= 14
    error_message = "snapshot_retain_count must be between 1 and 14 (cost guard)."
  }
}

variable "snapshot_target_tag_value" {
  description = "Value of the `Snapshot` tag DLM matches to select volumes. Must equal the tag set on the compute module's volume tag_specifications."
  type        = string
  default     = "hl-k3s"
}

variable "principal_boundary_arn" {
  description = "ARN of the IAM permissions boundary required on every IAM role created by this module. Null under LocalStack."
  type        = string
  default     = null
}
