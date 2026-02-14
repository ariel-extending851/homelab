# ==============================================================================
# Compute Module Variables
# ==============================================================================

variable "instance_type" {
  description = "EC2 instance type for k3s nodes"
  type        = string

  validation {
    condition     = can(regex("^t3\\.(micro|small|medium)$", var.instance_type))
    error_message = "Instance type must be t3.micro, t3.small, or t3.medium for cost optimization."
  }
}

variable "ebs_volume_size" {
  description = "EBS volume size in GB"
  type        = number

  validation {
    condition     = var.ebs_volume_size >= 30 && var.ebs_volume_size <= 100
    error_message = "EBS volume size must be between 30GB (AL2023 minimum) and 100GB."
  }
}

variable "spot_max_price" {
  description = "Maximum spot price per hour (leave empty for on-demand price)"
  type        = string
}

variable "ssh_key_name" {
  description = "Name for the SSH key pair"
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key content for EC2 access"
  type        = string
  sensitive   = true
}

variable "security_group_id" {
  description = "Security group ID for EC2 instances"
  type        = string
}

variable "k3s_token" {
  description = "Shared secret for k3s cluster"
  type        = string
  sensitive   = true
}

variable "k3s_version" {
  description = "k3s version to install (e.g., v1.28.5+k3s1)"
  type        = string

  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+\\+k3s[0-9]+$", var.k3s_version))
    error_message = "k3s version must be in format: vX.Y.Z+k3sN (e.g., v1.28.5+k3s1)."
  }
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key for joining nodes to the tailnet (Zero Trust mesh)"
  type        = string
  sensitive   = true
}

variable "localstack_test" {
  description = "Enable LocalStack testing mode (yes/no)"
  type        = string
  default     = "no"

  validation {
    condition     = contains(["yes", "no"], var.localstack_test)
    error_message = "localstack_test must be 'yes' or 'no'."
  }
}
