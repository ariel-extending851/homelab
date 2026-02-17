# /infra/aws-backend/main.tf
#
# This Terraform configuration creates the secure remote backend for our main
# infrastructure state. It should be applied once and then rarely touched.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # This backend configuration is local, as it creates its own backend.
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "aws" {
  region = "us-east-1"
}

# Generate a random suffix to ensure the S3 bucket name is globally unique.
resource "random_string" "suffix" {
  length  = 8
  special = false
  upper   = false
}

# Create a private S3 bucket to store the Terraform state.
resource "aws_s3_bucket" "terraform_state" {
  bucket = "homelab-terraform-state-${random_string.suffix.result}"

  # Prevent accidental deletion of the state bucket.
  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "Homelab Terraform State"
    Project = "Lab-DevOps-Pro"
  }
}

# Enable server-side encryption by default for all objects in the bucket.
resource "aws_s3_bucket_server_side_encryption_configuration" "state_encryption" {
  bucket = aws_s3_bucket.terraform_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Enable versioning to keep a history of the state file.
resource "aws_s3_bucket_versioning" "state_versioning" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

# Block all public access to the state bucket.
resource "aws_s3_bucket_public_access_block" "state_public_access" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Create a DynamoDB table for state locking.
resource "aws_dynamodb_table" "terraform_state_lock" {
  name         = "homelab-terraform-state-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Name    = "Homelab Terraform State Lock"
    Project = "Lab-DevOps-Pro"
  }
}

output "s3_bucket_name" {
  description = "The name of the S3 bucket for Terraform state."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "dynamodb_table_name" {
  description = "The name of the DynamoDB table for state locking."
  value       = aws_dynamodb_table.terraform_state_lock.name
}
