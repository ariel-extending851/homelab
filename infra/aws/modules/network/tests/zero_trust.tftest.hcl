# Tests for zero-trust network security configuration.
# Verifies that the security group has no public ingress — only self-referencing
# inter-node traffic is allowed. All external access must go through Tailscale.

mock_provider "aws" {}

# ── SG naming convention ──────────────────────────────────────────────────────

run "sg_naming" {
  assert {
    condition     = aws_security_group.k3s_cluster.name_prefix == "hl-k3s-cluster-"
    error_message = "Security group must have name_prefix 'hl-k3s-cluster-'"
  }
  assert {
    condition     = aws_security_group.k3s_cluster.tags["Name"] == "hl-k3s-cluster-sg"
    error_message = "Security group must be tagged Name=hl-k3s-cluster-sg"
  }
}

# ── Zero-trust: no public ingress ─────────────────────────────────────────────

run "zero_trust_ingress" {
  assert {
    condition     = length(aws_security_group.k3s_cluster.ingress) == 1
    error_message = "Security group must have exactly 1 ingress rule (self-referencing only)"
  }
  assert {
    condition     = one(aws_security_group.k3s_cluster.ingress).self == true
    error_message = "The single ingress rule must be self-referencing (inter-node traffic only)"
  }
}

# ── Egress allows outbound ────────────────────────────────────────────────────

run "egress_allowed" {
  assert {
    condition     = length(aws_security_group.k3s_cluster.egress) == 1
    error_message = "Security group must have exactly 1 egress rule"
  }
  assert {
    condition     = contains(one(aws_security_group.k3s_cluster.egress).cidr_blocks, "0.0.0.0/0")
    error_message = "Egress must allow all outbound traffic for Tailscale and container pulls"
  }
}
