# ==============================================================================
# FinOps Module Variables
# ==============================================================================

variable "alert_email" {
  description = "Email address that receives cost + security alerts via the hl-cost-alerts SNS topic. Non-secret alert destination — NOT a credential, so it is a plain variable, not SOPS-encrypted. Empty disables the email subscription. Confirming the subscription requires a one-time manual click."
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget in USD. Notifies at 80%/100% actual and 100% forecasted. Default sits above the ~$24.59/month scheduled run-rate to avoid false alarms."
  type        = number
  default     = 30

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be greater than 0."
  }
}

variable "billing_alarm_usd" {
  description = "CloudWatch billing alarm threshold in USD. Backstop above the budget; should be >= monthly_budget_usd."
  type        = number
  default     = 35

  validation {
    condition     = var.billing_alarm_usd > 0
    error_message = "billing_alarm_usd must be greater than 0."
  }
}

variable "anomaly_impact_threshold_usd" {
  description = "Minimum absolute dollar impact for a Cost Anomaly Detection alert to fire. Filters out day-to-day spot price jitter."
  type        = number
  default     = 10

  validation {
    condition     = var.anomaly_impact_threshold_usd > 0
    error_message = "anomaly_impact_threshold_usd must be greater than 0."
  }
}
