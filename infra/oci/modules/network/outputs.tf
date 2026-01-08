output "vcn_id" {
  value       = oci_core_vcn.main.id
  description = "The OCID of the main Virtual Cloud Network."
}
output "public_subnet_id" {
  value       = oci_core_subnet.public_subnet.id
  description = "The OCID of the public subnet."
}
output "private_subnet_id" {
  value       = oci_core_subnet.private_subnet.id
  description = "The OCID of the private subnet."
}
