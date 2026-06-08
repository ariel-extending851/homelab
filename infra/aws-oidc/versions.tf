terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.49"
    }
  }

  # Local backend — apply once manually, like infra/aws-backend.
  # Do NOT use the S3 backend here; this module bootstraps the role that
  # grants CI access to that bucket.
  backend "local" {}
}

provider "aws" {
  region = "us-east-1"

  # FinOps tagging policy — applied to every resource in this module.
  # Resource-level `tags = {}` blocks merge with these defaults; explicit
  # keys win on conflict. Environment is "Prod" because these IAM roles
  # gate production deploys (the staging-deploy Environment also reuses
  # the same apply role; pick Prod as the highest-blast-radius caller).
  default_tags {
    tags = {
      Project     = "homelab"
      Environment = "Prod"
      Service     = "ci-cd-oidc"
    }
  }
}
