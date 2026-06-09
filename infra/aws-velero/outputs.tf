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

output "k3s_snapshot_aws_access_key_id" {
  description = "Access key ID for the hl-k3s-snapshot IAM user (bootstrap into k8s/apps/k3s-snapshot/secret.yaml via make k3s-snapshot-bootstrap-secret)."
  value       = aws_iam_access_key.k3s_snapshot.id
}

output "k3s_snapshot_aws_secret_access_key" {
  description = "Secret access key for the hl-k3s-snapshot IAM user (bootstrap into k8s/apps/k3s-snapshot/secret.yaml via make k3s-snapshot-bootstrap-secret)."
  value       = aws_iam_access_key.k3s_snapshot.secret
  sensitive   = true
}

output "ssm_activation_id" {
  description = "SSM hybrid-activation ID for registering the Pis (bootstrap into group_vars via make ssm-activation-bootstrap)."
  value       = aws_ssm_activation.pi.id
  sensitive   = true
}

output "ssm_activation_code" {
  description = "SSM hybrid-activation code — one-time registration credential for the Pis."
  value       = aws_ssm_activation.pi.activation_code
  sensitive   = true
}
