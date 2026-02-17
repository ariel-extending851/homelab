# ==============================================================================
# Scheduler Module Outputs
# ==============================================================================

output "lambda_function_name" {
  description = "Name of the Lambda scheduler function"
  value       = aws_lambda_function.scheduler.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda scheduler function"
  value       = aws_lambda_function.scheduler.arn
}

output "lambda_function_url" {
  description = "HTTP URL for manual Lambda invocation"
  value       = aws_lambda_function_url.scheduler.function_url
}

output "manual_start_command" {
  description = "AWS CLI command to manually start instances (requires IAM credentials)"
  value       = "aws lambda invoke --function-name ${aws_lambda_function.scheduler.function_name} --payload '{\"action\":\"start\"}' --cli-binary-format raw-in-base64-out /dev/stdout"
}

output "manual_stop_command" {
  description = "AWS CLI command to manually stop instances (requires IAM credentials)"
  value       = "aws lambda invoke --function-name ${aws_lambda_function.scheduler.function_name} --payload '{\"action\":\"stop\"}' --cli-binary-format raw-in-base64-out /dev/stdout"
}

output "manual_status_command" {
  description = "AWS CLI command to check instance status (requires IAM credentials)"
  value       = "aws lambda invoke --function-name ${aws_lambda_function.scheduler.function_name} --payload '{\"action\":\"status\"}' --cli-binary-format raw-in-base64-out /dev/stdout"
}

output "schedule_summary" {
  description = "Summary of the configured schedule"
  value       = "Instances start at ${var.schedule_start_hour}:00 and stop at ${var.schedule_stop_hour}:00 ${var.schedule_timezone} daily"
}
