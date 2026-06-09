# ==============================================================================
# ECR Module Variables
# ==============================================================================

variable "repository_names" {
  description = "ECR repository names to create. Each must use the hl- prefix + kebab-case per docs/CONVENTIONS.md."
  type        = list(string)
  default     = ["hl-apps"]

  validation {
    condition     = alltrue([for n in var.repository_names : can(regex("^hl-[a-z0-9-]+$", n))])
    error_message = "Every repository name must start with 'hl-' and be lowercase kebab-case."
  }
}

variable "keep_image_count" {
  description = "Maximum number of images to retain per repository before the lifecycle policy expires the oldest. Keeps storage under the 500 MB free tier."
  type        = number
  default     = 10

  validation {
    condition     = var.keep_image_count >= 1 && var.keep_image_count <= 100
    error_message = "keep_image_count must be between 1 and 100."
  }
}
