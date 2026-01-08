resource "oci_identity_user" "terraform_bot" {
  description = "Automated user for Terraform operations"
  name        = "terraform-bot"
  email       = "agfonseca.ethanol119@aleeas.com"
}

resource "oci_identity_group" "homelab_admins" {
  description = "Group for Homelab automation administrators"
  name        = "homelab-admins"
}

resource "oci_identity_user_group_membership" "terraform_bot_membership" {
  group_id = oci_identity_group.homelab_admins.id
  user_id  = oci_identity_user.terraform_bot.id
}

resource "oci_identity_policy" "homelab_policy" {
  compartment_id = var.tenancy_ocid
  description    = "Policy for Homelab automation"
  name           = "homelab-policy"
  statements     = [
    "Allow group homelab-admins to manage all-resources in tenancy"
  ]
}

output "terraform_bot_ocid" {
  value = oci_identity_user.terraform_bot.id
  description = "OCID of the created Terraform Bot user"
}
