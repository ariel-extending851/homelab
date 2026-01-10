data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_id
}
data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_id
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = var.instance_shape
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
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
    assign_public_ip = true # Precisamos de IP público para acessar via SSH inicialmente
    display_name     = "${var.label_prefix}-k3s-node-${count.index}-vnic"
    hostname_label   = "k3s-node-${count.index}" # DNS interno
  }
  source_details {
    source_type = "image"
    source_id   = data.oci_core_images.ubuntu_arm.images[0].id
  }
  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    # user_data           = ...
  }
}
