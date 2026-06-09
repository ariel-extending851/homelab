# Tests for the SSM hybrid-activation break-glass additions to infra/aws-velero.
# Mocked AWS provider — no real API calls.

mock_provider "aws" {}

# The principal-boundary ARN flows into aws_iam_role.permissions_boundary, which
# the provider ARN-validates at apply — give the mocked data source a real ARN.
override_data {
  target = data.aws_iam_policy.principal_boundary
  values = {
    arn = "arn:aws:iam::123456789012:policy/homelab-principal-boundary"
  }
}

run "ssm_role_and_activation_are_correct" {
  command = apply

  assert {
    condition     = aws_iam_role.ssm_hybrid_pi.name == "hl-ssm-hybrid-pi"
    error_message = "SSM role must be named hl-ssm-hybrid-pi."
  }

  assert {
    condition     = aws_iam_role.ssm_hybrid_pi.permissions_boundary == data.aws_iam_policy.principal_boundary.arn
    error_message = "SSM role must carry the homelab principal boundary."
  }

  assert {
    condition     = strcontains(aws_iam_role.ssm_hybrid_pi.assume_role_policy, "ssm.amazonaws.com")
    error_message = "SSM role trust must allow the ssm.amazonaws.com service principal."
  }

  assert {
    condition     = aws_iam_role_policy_attachment.ssm_hybrid_pi_core.policy_arn == "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
    error_message = "SSM role must attach AmazonSSMManagedInstanceCore (free standard tier)."
  }

  assert {
    condition     = aws_ssm_activation.pi.registration_limit == 2
    error_message = "Activation must allow exactly the two Pis to register."
  }
}
