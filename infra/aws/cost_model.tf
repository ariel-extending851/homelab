variable "is_cost_scan" {
  description = "Define if have to create new instances for cost scanning"
  type        = bool
  default     = false
}

resource "aws_instance" "shadow_server" {
  count         = var.is_cost_scan ? 1 : 0
  ami           = "ami-unused"
  instance_type = var.server_instance_type

  root_block_device {
    volume_size = var.ebs_volume_size
    volume_type = "gp3"
  }
}

resource "aws_instance" "shadow_agent" {
  count = var.is_cost_scan ? 1 : 0
  ami   = "ami-unused"

  instance_type = var.agent_instance_type

  root_block_device {
    volume_size = var.ebs_volume_size
    volume_type = "gp3"
  }
}
