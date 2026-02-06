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

  display_name = "${var.label_prefix}-k3s-node-${format("%02d", count.index + 1)}"
  shape        = var.instance_shape

  shape_config {
    ocpus         = var.instance_ocpus      # 2 OCPUs per instance (Always Free: 4 total)
    memory_in_gbs = var.instance_memory_gbs # 12 GB per instance (Always Free: 24 GB total)
  }

  create_vnic_details {
    subnet_id        = var.subnet_id
    assign_public_ip = true
    display_name     = "${var.label_prefix}-k3s-node-${format("%02d", count.index + 1)}-vnic"
    hostname_label   = "k3s-node-${format("%02d", count.index + 1)}"
  }

  source_details {
    source_type = "image"
    source_id   = var.source_id # ARM64 Ubuntu 24.04 image OCID
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  launch_options {
    is_pv_encryption_in_transit_enabled = true
    network_type                        = "PARAVIRTUALIZED"
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/templates/user_data.tftpl", {
      tailscale_auth_key = var.tailscale_auth_key
    }))
  }

  # Lifecycle configuration
  lifecycle {
    # Ignore changes to metadata to prevent recreation on cloud-init changes
    ignore_changes = [metadata]

    # Optional: Prevent accidental destruction after migration is complete
    # Uncomment after successful ARM migration:
    # prevent_destroy = true

    # NOTE: replace_triggered_by cannot reference self.shape/self.source_details
    # For architecture changes (x86 -> ARM), use manual taint:
    #   terraform taint 'module.k3s_nodes.oci_core_instance.k3s_node[0]'
    #   terraform taint 'module.k3s_nodes.oci_core_instance.k3s_node[1]'
  }
}
