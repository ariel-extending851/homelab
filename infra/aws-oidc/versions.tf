terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Local backend — apply once manually, like infra/aws-backend.
  # Do NOT use the S3 backend here; this module bootstraps the role that
  # grants CI access to that bucket.
  backend "local" {}
}

provider "aws" {
  region = "us-east-1"
}
