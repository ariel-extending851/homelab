# Tests for the ecr module. Mocked AWS provider — no real API calls.

mock_provider "aws" {}

run "repo_hardened_defaults" {
  variables {
    repository_names = ["hl-apps"]
    keep_image_count = 10
  }
  command = plan

  assert {
    condition     = aws_ecr_repository.repos["hl-apps"].image_tag_mutability == "IMMUTABLE"
    error_message = "ECR repos must use IMMUTABLE tags for reproducible deploys."
  }

  assert {
    condition     = aws_ecr_repository.repos["hl-apps"].image_scanning_configuration[0].scan_on_push == true
    error_message = "ECR repos must enable free basic scan-on-push."
  }
}

run "non_hl_prefix_rejected" {
  variables {
    repository_names = ["badname"]
  }
  command         = plan
  expect_failures = [var.repository_names]
}

run "zero_keep_count_rejected" {
  variables {
    keep_image_count = 0
  }
  command         = plan
  expect_failures = [var.keep_image_count]
}
