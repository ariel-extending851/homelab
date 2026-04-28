# ==============================================================================
# AWS Infrastructure Variables (Non-Sensitive)
# ==============================================================================
# NOTE: All sensitive variables (SSH keys, tokens) are now loaded
# from SOPS-encrypted file (terraform.tfvars.sops.yaml) via data.sops_file.secrets
# ==============================================================================

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "server_instance_type" {
  description = "EC2 instance type for k3s server (control plane)"
  type        = string
  default     = "t3.medium"

  validation {
    condition     = can(regex("^t3\\.(micro|small|medium)$", var.server_instance_type))
    error_message = "Instance type must be t3.micro, t3.small, or t3.medium for cost optimization."
  }
}

variable "agent_instance_type" {
  description = "EC2 instance type for k3s agent (worker nodes)"
  type        = string
  default     = "t3.small"

  validation {
    condition     = can(regex("^t3\\.(micro|small|medium)$", var.agent_instance_type))
    error_message = "Instance type must be t3.micro, t3.small, or t3.medium for cost optimization."
  }
}

variable "ebs_volume_size" {
  description = "EBS volume size in GB"
  type        = number
  default     = 30

  validation {
    condition     = var.ebs_volume_size >= 30 && var.ebs_volume_size <= 100
    error_message = "EBS volume size must be between 30GB and 100GB (practical minimum for k3s cluster, AWS absolute minimum is 8GB)."
  }
}

variable "spot_max_price" {
  description = "Maximum spot price per hour (leave empty for on-demand price)"
  type        = string
  default     = "" # Empty = on-demand price as max
}

variable "ssh_key_name" {
  description = "Name for the SSH key pair"
  type        = string
  default     = "hl-homelab-key"
}

# ==============================================================================
# NOTE: SSH and k3s API CIDR variables removed - Zero Trust architecture
# All access is through Tailscale mesh (WireGuard encrypted).
# Emergency access via AWS SSM Session Manager (IAM-authenticated).
# No public ports are exposed in the security group.
# ==============================================================================

variable "k3s_version" {
  description = "k3s version to install (e.g., v1.28.5+k3s1)"
  type        = string
  default     = "v1.34.3+k3s1"

  validation {
    condition     = can(regex("^v[0-9]+\\.[0-9]+\\.[0-9]+\\+k3s[0-9]+$", var.k3s_version))
    error_message = "k3s version must be in format: vX.Y.Z+k3sN (e.g., v1.28.5+k3s1)."
  }
}

# ==============================================================================
# Instance Scheduling Configuration
# ==============================================================================
variable "enable_scheduling" {
  description = "Enable automated instance start/stop scheduling to reduce costs"
  type        = bool
  default     = true
}

variable "schedule_timezone" {
  description = "Timezone for scheduling (IANA format, e.g., America/Sao_Paulo)"
  type        = string
  default     = "America/Sao_Paulo" # Brazil timezone (BRT/BRST)
}

variable "schedule_start_hour" {
  description = "Hour to start instances (0-23, in schedule_timezone)"
  type        = number
  default     = 10 # 10 AM

  validation {
    condition     = var.schedule_start_hour >= 0 && var.schedule_start_hour <= 23
    error_message = "schedule_start_hour must be between 0 and 23."
  }
}

variable "schedule_stop_hour" {
  description = "Hour to stop instances (0-23, in schedule_timezone)"
  type        = number
  default     = 21 # 9 PM

  validation {
    condition     = var.schedule_stop_hour >= 0 && var.schedule_stop_hour <= 23
    error_message = "schedule_stop_hour must be between 0 and 23."
  }
}

# ==============================================================================
# LocalStack Testing Configuration
# ==============================================================================
variable "ssm_s3_bucket" {
  description = "S3 bucket name used by SSM Session Manager for stdin/stdout relay (Ansible SSM connection plugin). ⚠️ MUST be a separate bucket from the Terraform state bucket to prevent nodes from accessing decrypted secrets in state files."
  type        = string
  default     = "homelab-ssm-transfer-bucket"
}

variable "velero_backup_bucket" {
  description = "S3 bucket name for Velero cluster backups. Versioned, encrypted, lifecycle-tiered (Standard → IA → Glacier → expire 365d)."
  type        = string
  default     = "homelab-velero-backups"
}

variable "localstack_test" {
  description = "Enable LocalStack testing mode (yes/no). When 'yes', uses mock secrets instead of SOPS."
  type        = string
  default     = "no"

  validation {
    condition     = contains(["yes", "no"], var.localstack_test)
    error_message = "localstack_test must be 'yes' or 'no'."
  }
}
