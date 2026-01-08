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
}
