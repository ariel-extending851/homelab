# Staging overrides for the homelab AWS workspace.
#
# Usage: see Makefile targets `terraform-staging-*` (they select the
# `staging` Terraform workspace and pass `-var-file=staging.tfvars`).
#
# Backend state is namespaced automatically: a `terraform.workspace`
# value of "staging" causes Terraform to write to
# env:/staging/homelab/terraform.tfstate inside the same S3 bucket.
#
# IMPORTANT — single-account caveat: module-internal name tags (e.g.,
# k3s-server-aws) are not yet parameterised by workspace, so staging
# resources collide with prod when both run simultaneously in one AWS
# account. Bring staging up only when prod is destroyed, OR run staging
# in a separate AWS account. Full multi-account / canary support is
# tracked as the remaining Phase 5 work in the QA gap-closure plan.

# Smaller instances to reduce idle cost while staging is up.
# Note: the fleet override list in modules/compute/main.tf floors at 2 GiB
# (t3.small / t3a.small / t3.medium). The launch template uses these vars,
# but spot fleet substitution is bounded by the overrides — so even if you
# set agent_instance_type = "t3.micro" here, the running instance will be
# t3.small or larger. Keep these aligned to avoid confusion at plan time.
server_instance_type = "t3.small"
agent_instance_type  = "t3.small"
ebs_volume_size      = 30

# Aggressive shutdown window: 22:00 → 07:00 BRT (vs prod 21:00 → 10:00).
schedule_start_hour = 7
schedule_stop_hour  = 22

# Distinct SSM relay + Velero buckets so staging never overlaps prod state.
ssm_s3_bucket        = "homelab-ssm-transfer-bucket-staging"
velero_backup_bucket = "homelab-velero-backups-staging"

# Stable SSH key name across env to keep tooling consistent.
ssh_key_name = "hl-homelab-key"
