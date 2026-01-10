output "k3s_node_public_ips" {
  value       = module.k3s_nodes.instance_public_ips
  description = "Public IPs of the created k3s nodes"
}

output "k3s_node_private_ips" {
  value       = module.k3s_nodes.instance_private_ips
  description = "Private IPs of the created k3s nodes"
}

output "k3s_node_names" {
  value       = module.k3s_nodes.instance_names
  description = "Display names of the created k3s nodes"
}
