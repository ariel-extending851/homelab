# ==============================================================================
# Observability Module Outputs
# ==============================================================================

output "bucket_id" {
  description = "Name of the cold-storage S3 bucket (consumed by the Alloy DaemonSet env)."
  value       = aws_s3_bucket.cold_storage.id
}

output "bucket_arn" {
  description = "ARN of the cold-storage S3 bucket (consumed by the k3s_node IAM role policy)."
  value       = aws_s3_bucket.cold_storage.arn
}

output "bucket_regional_domain_name" {
  description = "Regional domain name of the bucket (used by Alloy's awss3 exporter endpoint)."
  value       = aws_s3_bucket.cold_storage.bucket_regional_domain_name
}
