# tflint config — repo root, conservative rules.
#
# Wired via `make validate-terraform-all` (Makefile:569) and
# `setup-ci-deps-terraform` (Makefile:181). To run locally:
#   cd infra/aws && tflint --init && tflint --format=compact
#
# Rule strategy:
#   - terraform_* core rules: enabled (low-risk hygiene checks).
#   - terraform-linters/tflint-ruleset-aws: pulled via `tflint --init`
#     so AWS-specific rules (invalid instance types, deprecated AMIs)
#     are also validated.
#   - Disable rules that fight the codebase's existing conventions
#     rather than rewriting working code to satisfy the linter.

config {
  format     = "compact"
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.40.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}

# Variables and outputs SHOULD be documented; warn when they aren't.
rule "terraform_documented_outputs" {
  enabled = true
}

rule "terraform_documented_variables" {
  enabled = true
}

# Catch dead code: unused vars, locals, data sources.
rule "terraform_unused_declarations" {
  enabled = true
}

# Pin terraform + provider versions to avoid surprise breaking-change adoptions.
rule "terraform_required_version" {
  enabled = true
}

rule "terraform_required_providers" {
  enabled = true
}

# Module names: snake_case is the de-facto repo convention.
rule "terraform_naming_convention" {
  enabled = true
  format  = "snake_case"
}
