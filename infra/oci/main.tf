terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "7.29.0"
    }
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
    sops = {
      source  = "carlpett/sops"
      version = "~> 0.7.0"
    }
  }
}

# SOPS Provider Configuration
provider "sops" {}

# Load secrets from SOPS-encrypted file
data "sops_file" "secrets" {
  source_file = "${path.module}/terraform.tfvars.sops.yaml"
}

# Local values for secrets
locals {
  secrets = data.sops_file.secrets.data
}

provider "oci" {
  # Configuration using secrets from SOPS
  tenancy_ocid     = local.secrets["tenancy_ocid"]
  user_ocid        = local.secrets["user_ocid"]
  fingerprint      = local.secrets["fingerprint"]
  private_key_path = local.secrets["private_key_path"]
  region           = var.region
}

#data "oci_core_images" "ubuntu_24_04" {
#  compartment_id           = local.secrets["compartment_id"]
#  operating_system         = "Canonical Ubuntu"
#  operating_system_version = "24.04"
#  shape                    = var.instance_shape
#  sort_by                  = "TIMECREATED"
#  sort_order               = "DESC"
#}

module "main_network" {
  source              = "./modules/network"
  compartment_id      = local.secrets["compartment_id"]
  vcn_cidr            = "10.0.0.0/16"
  public_subnet_cidr  = "10.0.1.0/24"
  private_subnet_cidr = "10.0.2.0/24"
  tailscale_auth_key  = local.secrets["tailscale_auth_key"]
  label_prefix        = "hl"
}

module "k3s_nodes" {
  source = "./modules/compute"

  compartment_id = local.secrets["compartment_id"]
  subnet_id      = module.main_network.public_subnet_id
  ssh_public_key = file(local.secrets["public_key_path"])
  label_prefix   = "hl"

  instance_shape = var.instance_shape

  instance_count = 1

  source_id = var.instance_image_id

  tailscale_auth_key = local.secrets["tailscale_auth_key"]
}

resource "null_resource" "ansible_inventory_generator" {
  depends_on = [module.k3s_nodes]

  provisioner "local-exec" {
    command     = <<EOT
      echo "[k3s_master]" > hosts.ini
      echo "${module.k3s_nodes.instance_public_ips[0]} ansible_user=opc" >> hosts.ini
      echo "" >> hosts.ini
      echo "[k3s_node]" >> hosts.ini
      ${join("\n", formatlist("echo \"%s ansible_user=opc\" >> hosts.ini", slice(module.k3s_nodes.instance_public_ips, 1, length(module.k3s_nodes.instance_public_ips))))}
    EOT
    working_dir = path.module
  }
}
