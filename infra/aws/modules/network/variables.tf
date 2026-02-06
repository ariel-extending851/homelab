# ==============================================================================
# Network Module Variables
# ==============================================================================

variable "ssh_allowed_cidr" {
  description = "CIDR blocks allowed to SSH into instances"
  type        = list(string)

  validation {
    condition     = length(var.ssh_allowed_cidr) > 0
    error_message = "At least one CIDR block must be specified."
  }
}

variable "k3s_api_allowed_cidr" {
  description = "CIDR blocks allowed to access k3s API server"
  type        = list(string)

  validation {
    condition     = length(var.k3s_api_allowed_cidr) > 0
    error_message = "At least one CIDR block must be specified."
  }
}
