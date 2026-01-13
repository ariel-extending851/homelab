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

#data "oci_core_images" "ubuntu_24_04" {
#  compartment_id           = var.compartment_id
#  operating_system         = "Canonical Ubuntu"
#  operating_system_version = "24.04"
#  shape                    = var.instance_shape
#  sort_by                  = "TIMECREATED"
#  sort_order               = "DESC"
#}

module "main_network" {
  source              = "./modules/network"
  compartment_id      = var.compartment_id
  vcn_cidr            = "10.0.0.0/16"
  public_subnet_cidr  = "10.0.1.0/24"
  private_subnet_cidr = "10.0.2.0/24"
  tailscale_auth_key  = var.tailscale_auth_key
  label_prefix        = "hl"
}

module "k3s_nodes" {
  source = "./modules/compute"

  compartment_id = var.compartment_id
  subnet_id      = module.main_network.public_subnet_id
  ssh_public_key = file("~/.ssh/omarchy_pc.pub")
  label_prefix   = "hl"

  instance_shape = var.instance_shape

  instance_count = 2

  source_id = var.instance_image_id
}
