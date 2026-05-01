# ==============================================================================
# Audit Module Outputs
# ==============================================================================

output "trail_name" {
  description = "Name of the CloudTrail trail."
  value       = aws_cloudtrail.main.name
}

output "trail_arn" {
  description = "ARN of the CloudTrail trail."
  value       = aws_cloudtrail.main.arn
}

output "trail_bucket_name" {
  description = "S3 bucket holding CloudTrail logs."
  value       = aws_s3_bucket.trail.id
}

output "guardduty_detector_id" {
  description = "ID of the GuardDuty detector."
  value       = aws_guardduty_detector.main.id
}
