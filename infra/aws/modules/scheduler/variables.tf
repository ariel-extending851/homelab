# ==============================================================================
# Scheduler Module Variables
# ==============================================================================

variable "server_instance_id" {
  description = "EC2 instance ID for k3s server"
  type        = string
}

variable "agent_instance_id" {
  description = "EC2 instance ID for k3s agent"
  type        = string
}

variable "schedule_timezone" {
  description = "Timezone for scheduling (IANA format)"
  type        = string
  default     = "America/Sao_Paulo"
}

variable "schedule_start_hour" {
  description = "Hour to start instances (0-23, in local timezone)"
  type        = number
  default     = 10

  validation {
    condition     = var.schedule_start_hour >= 0 && var.schedule_start_hour <= 23
    error_message = "schedule_start_hour must be between 0 and 23."
  }
}

variable "schedule_stop_hour" {
  description = "Hour to stop instances (0-23, in local timezone)"
  type        = number
  default     = 21

  validation {
    condition     = var.schedule_stop_hour >= 0 && var.schedule_stop_hour <= 23
    error_message = "schedule_stop_hour must be between 0 and 23."
  }
}
