packer {
  required_plugins {
    qemu = {
      version = ">= 1.0.9"
      source  = "github.com/hashicorp/qemu"
    }
    vagrant = {
      version = ">= 1.1.3"
      source  = "github.com/hashicorp/vagrant"
    }
  }
}

source "qemu" "fedora-kickstart" {
  iso_url      = "https://edgeuno-bog2.mm.fcix.net/fedora/linux/releases/42/Server/x86_64/iso/Fedora-Server-netinst-x86_64-42-1.1.iso"
  iso_checksum = "sha256:231f3e0d1dc8f565c01a9f641b3d16c49cae44530074bc2047fe2373a721c82f"

  http_directory = "."

  vm_name          = "fedora-kickstart-build.qcow2"
  output_directory = "output_fedora"

  accelerator = "kvm"
  disk_size   = "10G"
  format      = "qcow2"
  memory      = 4096

  headless         = true
  vnc_bind_address = "127.0.0.1"

  net_device = "virtio-net-pci"

  ssh_username = "ariel"
  ssh_password = "fedora"
  ssh_timeout  = "30m"

  boot_wait = "5s"
  boot_command = [
    "e",
    "<down><down><end>",
    " inst.ks=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ks.cfg",
    "<F10>"
  ]

  shutdown_timeout = "20m"
}

build {
  sources = ["source.qemu.fedora-kickstart"]

  post-processor "vagrant" {
    output = "fedora-libvirt.box"

    vagrantfile_template = "vagrantfile-libvirt.template"
  }
}
