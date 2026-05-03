# ==============================================================================
# Tailscale Configuration
# ==============================================================================
# This file configures Tailscale network policies and ACLs
# Requires: tailscale_api_key in terraform.tfvars.sops.yaml

# Configure the Tailscale provider
provider "tailscale" {
  api_key = local.secrets["tailscale_api_key"]
  tailnet = "ariel-extending851.github" # Your tailnet name
}

# Apply the ACL policy
#
# Disabled 2026-05-03: live tailnet ACL is richer than acl.json (declares
# tag:server for EC2, tagged-devices for RPi, plus user-managed rules for
# phones/TVs). Importing + applying acl.json would overwrite all those
# rules and break connectivity for every device. ACL stays managed in the
# Tailscale admin panel until a follow-up PR syncs acl.json with live state.
#
# resource "tailscale_acl" "homelab_acl" {
#   acl = file("${path.module}/acl.json")
# }
