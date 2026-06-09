# ==============================================================================
# ECR Module — Private Container Registry
# ==============================================================================
# A private registry so the cluster can pull its own images without hitting the
# Docker Hub anonymous rate limit (a recurring k3s pain point). Near-free: the
# ECR free tier is 500 MB-month of storage for 12 months, then ~$0.10/GB-month;
# intra-region pulls to the EC2 nodes are free. Basic scan-on-push is free —
# enhanced/Inspector scanning is the paid tier and is deliberately NOT enabled.
#
# The k3s_node IAM role gets pull permissions wired in modules/compute via the
# repository_arns output (mirrors the observability-bucket wiring pattern).
# ==============================================================================

resource "aws_ecr_repository" "repos" {
  for_each = toset(var.repository_names)

  name                 = each.value
  image_tag_mutability = "IMMUTABLE" # tags can't be overwritten — reproducible deploys

  image_scanning_configuration {
    scan_on_push = true # basic scanning is free
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = each.value
  }
}

# Lifecycle policy keeps the repo under the 500 MB free-tier ceiling: drop
# untagged layers fast, and cap the number of retained tagged images.
resource "aws_ecr_lifecycle_policy" "expire" {
  for_each = aws_ecr_repository.repos

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images older than 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep only the most recent ${var.keep_image_count} images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.keep_image_count
        }
        action = { type = "expire" }
      },
    ]
  })
}
