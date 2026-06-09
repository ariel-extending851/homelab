# ==============================================================================
# FinOps Module Outputs
# ==============================================================================

output "cost_alerts_topic_arn" {
  description = "ARN of the shared hl-cost-alerts SNS topic (cost + security alerts)."
  value       = aws_sns_topic.cost_alerts.arn
}

output "budget_name" {
  description = "Name of the monthly cost budget."
  value       = aws_budgets_budget.monthly.name
}

output "anomaly_monitor_arn" {
  description = "ARN of the Cost Anomaly Detection monitor."
  value       = aws_ce_anomaly_monitor.services.arn
}

output "access_analyzer_arn" {
  description = "ARN of the IAM Access Analyzer (external-access, ACCOUNT type)."
  value       = aws_accessanalyzer_analyzer.account.arn
}

output "billing_alarm_name" {
  description = "Name of the CloudWatch billing alarm."
  value       = aws_cloudwatch_metric_alarm.billing.alarm_name
}
