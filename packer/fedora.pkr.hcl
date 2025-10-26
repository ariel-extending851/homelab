packer {
  required_plugins {
    qemu = {
      version = "~> 1"
      source  = "github.com/hashicorp/qemu"
    }
    vagrant = {
      version = ">= 1.1.3"
      source  = "github.com/hashicorp/vagrant"
    }
  }
}

# --- Variáveis ---
variable "headless" {
  type    = bool
  default = true
}
variable "vm_name_base" {
  type    = string
  default = "fedora-42-cloud-x86_64"
}
variable "fedora_cloud_image_url" {
  type    = string
  default = "https://download.fedoraproject.org/pub/fedora/linux/releases/42/Cloud/x86_64/images/Fedora-Cloud-Base-Generic-42-1.1.x86_64.qcow2"
}
variable "fedora_cloud_checksum_url" {
  type    = string
  default = "https://download.fedoraproject.org/pub/fedora/linux/releases/42/Cloud/x86_64/images/Fedora-Cloud-42-1.1-x86_64-CHECKSUM"
}
# Variável para o usuário inicial (cloud image default)
variable "initial_ssh_username" {
  type    = string
  default = "fedora" # Usuário padrão da Fedora Cloud Image
}
# Senha temporária para o usuário inicial (usada pelo cloud-init)
variable "initial_ssh_password" {
  type    = string
  default = "fedora" # Senha temporária, será usada pelo Packer para conectar
}

variable "final_ssh_password" {
  type    = string
  default = "fedora" # Pode ser a mesma ou diferente
}

# --- Fonte QEMU (Com Cloud-Init) ---
source "qemu" "fedora-cloud" {
  cpu_model    = "host"
  machine_type = "q35"

  # Configuração da Imagem Base
  iso_url      = var.fedora_cloud_image_url
  iso_checksum = "file:${var.fedora_cloud_checksum_url}"
  disk_image   = true

  # Disco Final
  disk_size        = "10G"
  disk_compression = true
  format           = "qcow2"

  # Gerais
  headless         = var.headless
  vm_name          = "${var.vm_name_base}.qcow2"
  output_directory = "../builds/output-${var.vm_name_base}"

  # Rede
  net_device = "virtio-net-pci"

  # --- CLOUD-INIT: Anexa o CD cidata.iso ---
  # Isso fornece a configuração inicial para pular a tela manual
  qemuargs = [
    ["-cdrom", "boot-${var.vm_name_base}/cidata.iso"]
  ]
  # --- FIM DO CLOUD-INIT ---

  # SSH (Conecta como usuário inicial configurado pelo cloud-init)
  ssh_username = var.initial_ssh_username
  ssh_password = var.initial_ssh_password
  ssh_timeout  = "10m"

  # Desligamento (Usará sudo)
  shutdown_command = "sudo shutdown -P now"

  # VNC
  # vnc_bind_address = "127.0.0.1"
}

# --- Fontes de Arquivo para Cloud-Init ---
# Cria o arquivo user-data para o cloud-init
source "file" "user_data" {
  content = <<-EOF
#cloud-config
# Configura o usuário inicial ('fedora') com senha e permite login SSH com senha
user: ${var.initial_ssh_username}
password: ${var.initial_ssh_password}
chpasswd: { expire: False }
ssh_pwauth: True
# Garante que o usuário possa usar sudo (importante!)
sudo: ALL=(ALL) NOPASSWD:ALL 
EOF
  # Salva o arquivo em uma subpasta temporária
  target = "boot-${var.vm_name_base}/user-data"
}

# Cria o arquivo meta-data para o cloud-init
source "file" "meta_data" {
  content = <<-EOF
instance-id: packer-${var.vm_name_base}
local-hostname: ${var.vm_name_base}
EOF
  target  = "boot-${var.vm_name_base}/meta-data"
}

# --- Bloco Build (Com Cloud-Init ISO e Provisioners) ---
build {
  # Inclui as fontes de arquivo E a fonte qemu
  sources = ["source.qemu.fedora-cloud"]

  # --- Provisioner Local: Cria o cidata.iso ---
  # Roda ANTES da VM iniciar
  provisioner "shell-local" {
    inline = [
      "echo '--- Criando arquivos e cidata.iso para cloud-init ---'",
      # Cria o diretório
      "mkdir -p boot-${var.vm_name_base}",

      # Cria o arquivo user-data diretamente
      "cat <<EOF > boot-${var.vm_name_base}/user-data",
      "#cloud-config",
      "user: ${var.initial_ssh_username}",
      "password: ${var.initial_ssh_password}",
      "chpasswd: { expire: False }",
      "ssh_pwauth: True",
      "sudo: ALL=(ALL) NOPASSWD:ALL", // Mantém o sudo para o usuário inicial
      "EOF",

      # Cria o arquivo meta-data diretamente
      "cat <<EOF > boot-${var.vm_name_base}/meta-data",
      "instance-id: packer-${var.vm_name_base}",
      "local-hostname: ${var.vm_name_base}",
      "EOF",

      # Cria o ISO a partir dos arquivos recém-criados
      "genisoimage -output boot-${var.vm_name_base}/cidata.iso -input-charset utf-8 -volid cidata -joliet -rock boot-${var.vm_name_base}/user-data boot-${var.vm_name_base}/meta-data"
    ]
  }
  # --- FIM DO Provisioner Local ---

  # --- Provisioners SSH (Rodam DEPOIS que a VM inicia) ---
  # --- PROVISIONER CORRIGIDO: Criar usuário ariel ---
  provisioner "shell" {
    execute_command = "echo '${var.initial_ssh_password}' | {{ .Vars }} sudo -S -E sh -eux '{{ .Path }}'"
    inline = [
      "echo '--- Criando usuário ariel ---'",
      "sudo useradd -m -G wheel ariel",
      "echo '${var.final_ssh_password}' | sudo passwd --stdin ariel", # Correct variable
      "echo 'Usuário ariel criado com senha **sensível**'"
    ]
  }

  # --- PROVISIONER CORRIGIDO: Configurar sudoers.d/vagrant ---
  provisioner "shell" {
    execute_command = "echo '${var.initial_ssh_password}' | {{ .Vars }} sudo -S -E sh -eux '{{ .Path }}'"
    inline = [
      "echo '--- Configurando sudo NOPASSWD para Vagrant ---'",
      "echo '%wheel ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/vagrant",
      "sudo chmod 440 /etc/sudoers.d/vagrant"
    ]
  }

  # --- PROVISIONER CORRIGIDO: Desabilitar SELinux ---
  provisioner "shell" {
    execute_command = "echo '${var.initial_ssh_password}' | {{ .Vars }} sudo -S -E sh -eux '{{ .Path }}'"
    inline = [
      "echo '--- Desabilitando SELinux ---'",
      # Verifica se o arquivo existe antes de tentar modificá-lo
      "if [ -f /etc/selinux/config ]; then sudo sed -i 's/^SELINUX=enforcing/SELINUX=disabled/' /etc/selinux/config; fi",
      # Tenta desabilitar em tempo real, ignora erro se já estiver desabilitado
      "sudo setenforce 0 || echo 'SELinux já está permissivo ou desabilitado'"
    ]
  }

  # --- PROVISIONER CORRIGIDO: Instalar rsync ---
  provisioner "shell" {
    execute_command = "echo '${var.initial_ssh_password}' | {{ .Vars }} sudo -S -E sh -eux '{{ .Path }}'"
    inline = [
      "echo '--- Instalando rsync para Vagrant ---'",
      "sudo dnf install -y rsync"
    ]
  }
  # --- FIM DOS Provisioners SSH ---

  # Pós-Processador Vagrant
  post-processor "vagrant" {
    output               = "../builds/${var.vm_name_base}-libvirt.box"
    vagrantfile_template = "vagrantfile_template_placeholder" # Precisa existir
  }
}
