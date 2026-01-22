variable "tenancy_ocid" {
  type        = string
  description = "The OCID of your OCI tenancy."
  sensitive   = true
}
variable "user_ocid" {
  type        = string
  description = "The OCID of the user calling the provider."
  sensitive   = true
}
variable "fingerprint" {
  type        = string
  description = "The fingerprint of the API key used for authentication."
  sensitive   = true
}
variable "private_key_path" {
  type        = string
  description = "The absolute path to the private key file for OCI API authentication."
  sensitive   = true
}
variable "public_key_path" {
  type        = string
  description = "The absolute path to the public key file for OCI API authentication."
  sensitive   = true
}
variable "region" {
  type        = string
  description = "The OCI region where resources will be provisioned."
}
variable "compartment_id" {
  type        = string
  description = "The OCID of the compartment where resources will be created."

}
variable "tailscale_auth_key" {
  type        = string
  description = "auth key for tailscale"
  sensitive   = true
}
variable "instance_image_id" {
  description = "OCID da imagem (Ubuntu) para as maquinas"
  type        = string
}
variable "instance_shape" {
  description = "Shape da instancia (ex: VM.Standard3.Flex)"
  type        = string
  default     = "VM.Standard.E4.Flex"
}
