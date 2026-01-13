variable "compartment_id" {
  description = "OCID of the compartment"
  type        = string
}

variable "subnet_id" {
  description = "OCID of the subnet where instances will be created"
  type        = string
}

variable "ssh_public_key" {
  description = "SSH public key for instance access"
  type        = string
}

variable "instance_count" {
  description = "Number of instances to create"
  type        = number
  default     = 2
}

variable "instance_shape" {
  description = "Shape of the instance"
  type        = string
  default     = "VM.Standard.A1.Flex"
}

variable "instance_ocpus" {
  description = "Number of OCPUs"
  type        = number
  default     = 2
}

variable "instance_memory_gbs" {
  description = "Amount of Memory in GBs"
  type        = number
  default     = 12
}

variable "label_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "source_id" {
  description = "OCID da imagem a ser usada na instância"
  type        = string
}
