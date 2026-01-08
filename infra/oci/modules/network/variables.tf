variable "compartment_id" {
  type        = string
  description = "The OCID of the compartment where network resources will be provisioned."
}

variable "vcn_cidr" {
  type        = string
  description = "The CIDR block for the Virtual Cloud Network (VCN)."
}

variable "public_subnet_cidr" {
  type        = string
  description = "The CIDR block for the public subnet."
}

variable "private_subnet_cidr" {
  type        = string
  description = "The CIDR block for the private subnet."
}

variable "tailscale_auth_key" {
  type        = string
  description = "Tailscale authentication key for new instances to join the Tailnet."
  sensitive   = true
}

variable "label_prefix" {
  type        = string
  description = "Prefix to use for all resource names in this module (e.g., 'hl')."
}
