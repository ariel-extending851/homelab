output "velero_backup_bucket_name" {
  description = "S3 bucket name for Velero cluster backups."
  value       = aws_s3_bucket.velero_backups.id
}

output "velero_aws_access_key_id" {
  description = "Access key ID for the Velero IAM user (paste into k8s/apps/velero/secret.yaml then SOPS-encrypt)."
  value       = aws_iam_access_key.velero.id
}

output "velero_aws_secret_access_key" {
  description = "Secret access key for the Velero IAM user (paste into k8s/apps/velero/secret.yaml then SOPS-encrypt)."
  value       = aws_iam_access_key.velero.secret
  sensitive   = true
}
