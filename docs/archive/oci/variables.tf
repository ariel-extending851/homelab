# ==============================================================================
# OCI Infrastructure Variables (Non-Sensitive)
# ==============================================================================
# NOTE: All sensitive variables (OCIDs, API keys, tokens) are now loaded
# from SOPS-encrypted file (terraform.tfvars.sops.yaml) via data.sops_file.secrets
# ==============================================================================

variable "region" {
  type        = string
  default     = "sa-saopaulo-1"
  description = "The OCI region where resources will be provisioned."
}

variable "instance_image_id" {
  description = "OCID da imagem ARM64 Ubuntu 24.04 para VM.Standard.A1.Flex (Always Free)"
  default     = "ocid1.image.oc1.sa-saopaulo-1.aaaaaaaaaidkaxag5ju3kvdosvmi4dqxux6yhee7pjxkm4oqbbhmbb55an7a"
  type        = string
}

variable "instance_shape" {
  description = "Shape da instancia (VM.Standard.A1.Flex for ARM Always Free tier)"
  type        = string
  default     = "VM.Standard.A1.Flex"
}

# ==============================================================================
# GitHub Provider Variables (Non-Sensitive)
# ==============================================================================
# NOTE: github_token is loaded from SOPS-encrypted file
# ==============================================================================

variable "github_owner" {
  type        = string
  description = "GitHub repository owner (username or organization)"
  default     = "ariel99gf"
}
