terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "7.29.0"
    }
  }
}

provider "oci" {
  # Configuration options
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
  region           = var.region
}

module "main_network" {
  source              = "./modules/network"
  compartment_id      = var.compartment_id
  vcn_cidr            = "10.0.0.0/16"
  public_subnet_cidr  = "10.0.1.0/24"
  private_subnet_cidr = "10.0.2.0/24"
  tailscale_auth_key  = var.tailscale_auth_key
  label_prefix        = "hl"
}
