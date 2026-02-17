output "instance_public_ips" {
  value       = oci_core_instance.k3s_node[*].public_ip
  description = "Public IPs of the created instances"
}

output "instance_private_ips" {
  value       = oci_core_instance.k3s_node[*].private_ip
  description = "Private IPs of the created instances"
}

output "instance_names" {
  value       = oci_core_instance.k3s_node[*].display_name
  description = "Display names of the created instances"
}
