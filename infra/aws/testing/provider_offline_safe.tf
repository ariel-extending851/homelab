# provider_offline_safe.tf - Safe provider config for offline validation
# This file is conditionally used by the validate-terraform-all Makefile target
#
# All endpoints are intentionally disabled to prevent any real AWS/LocalStack connections
# during offline syntax validation. This overrides the LocalStack configuration.

provider "aws" {
  region = var.aws_region

  # ── Offline validation mode ──────────────────────────────────────────────
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  skip_region_validation      = true

  default_tags {
    tags = {
      Project     = "Lab-DevOps-Pro"
      ManagedBy   = "Terraform"
      Environment = "homelab"
    }
  }
}
