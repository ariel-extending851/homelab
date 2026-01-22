terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "= 7.29.0"
    }
  }
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_id
}
resource "oci_core_instance" "k3s_node" {
  count = var.instance_count

  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  compartment_id      = var.compartment_id

  display_name = "${var.label_prefix}-k3s-node-${count.index}"
  shape        = var.instance_shape

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }
  create_vnic_details {
    subnet_id        = var.subnet_id
    assign_public_ip = true
    display_name     = "${var.label_prefix}-k3s-node-${count.index}-vnic"
    hostname_label   = "k3s-node-${count.index}"
  }
  source_details {
    source_type = "image"
    source_id   = var.source_id
  }
  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/templates/user_data.tftpl", {
      tailscale_auth_key = var.tailscale_auth_key
    }))
  }
}
