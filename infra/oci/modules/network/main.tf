resource "oci_core_vcn" "main" {
  compartment_id = var.compartment_id
  cidr_block     = var.vcn_cidr
  display_name   = "${var.label_prefix}-main-vcn"
  dns_label      = "homelabvcn"
}
resource "oci_core_internet_gateway" "internet_gateway" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.label_prefix}-main-igw"
}
resource "oci_core_route_table" "route_table" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.main.id
  route_rules {
    network_entity_id = oci_core_internet_gateway.internet_gateway.id
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
  }
  display_name = "${var.label_prefix}-main-route-table"
}
resource "oci_core_security_list" "security_list" {
  compartment_id = var.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.label_prefix}-main-security-list"
  egress_security_rules {
    destination      = "0.0.0.0/0"
    protocol         = "all"
    destination_type = "CIDR_BLOCK"
  }
  ingress_security_rules {
    source      = var.vcn_cidr
    protocol    = "all"
    source_type = "CIDR_BLOCK"
  }
  ingress_security_rules {
    protocol    = "17"
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    stateless   = true
    udp_options {
      min = 41641
      max = 41641
    }
    description = "Tailscale Direct Connections"
  }
  #ingress_security_rules {
    #protocol    = "6"
    #source      = "0.0.0.0/0"
    #source_type = "CIDR_BLOCK"
    #tcp_options {
      #min = 22
      #max = 22
      #}
    #}
}
resource "oci_core_subnet" "public_subnet" {
  cidr_block        = var.public_subnet_cidr
  compartment_id    = var.compartment_id
  vcn_id            = oci_core_vcn.main.id
  display_name      = "${var.label_prefix}-main-public-subnet"
  route_table_id    = oci_core_route_table.route_table.id
  security_list_ids = [oci_core_security_list.security_list.id]

  dns_label         = "public"
}
resource "oci_core_subnet" "private_subnet" {
  cidr_block        = var.private_subnet_cidr
  compartment_id    = var.compartment_id
  vcn_id            = oci_core_vcn.main.id
  display_name      = "${var.label_prefix}-main-private-subnet"
  route_table_id    = oci_core_route_table.route_table.id
  security_list_ids = [oci_core_security_list.security_list.id]

  dns_label         = "private"
}
