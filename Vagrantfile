# -*- mode: ruby -*-
# vi: set ft=ruby :

Vagrant.configure("2") do |config|

  config.vm.box = "fedora-libvirt"

  config.vm.box_url = "file://#{__dir__}/builds/fedora-42-cloud-x86_64-libvirt.box"

  config.ssh.username = "ariel"
  config.ssh.password = "fedora"
  config.ssh.insert_key = true

  config.vm.provider "libvirt" do |libvirt|
    libvirt.memory = 4096
    libvirt.cpus = 2
  end

end
