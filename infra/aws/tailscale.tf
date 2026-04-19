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
resource "tailscale_acl" "homelab_acl" {
  acl = file("${path.module}/acl.json")
}
