terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "= 7.29.0"
    }
  }
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_id
}
resource "oci_core_instance" "k3s_node" {
  count = var.instance_count

  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  compartment_id      = var.compartment_id

  display_name = "${var.label_prefix}-k3s-node-${count.index}"
  shape        = var.instance_shape

  shape_config {
    ocpus         = var.instance_ocpus
    memory_in_gbs = var.instance_memory_gbs
  }
  create_vnic_details {
    subnet_id        = var.subnet_id
    assign_public_ip = true
    display_name     = "${var.label_prefix}-k3s-node-${count.index}-vnic"
    hostname_label   = "k3s-node-${count.index}"
  }
  source_details {
    source_type = "image"
    source_id   = var.source_id
  }
  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(<<-EOF
      #cloud-config
      runcmd:
        - |
          retry_command() {
            local max_attempts=20
            local sleep_time=10
            local attempt=1

            echo "Executando: $@"
            until "$@"; do
              if [ $attempt -ge $max_attempts ]; then
                echo "Falha no comando '$@' após $max_attempts tentativas."
                exit 1
              fi

              echo "Comando falhou (Tentativa $attempt/$max_attempts). O apt pode estar ocupado. Aguardando $${sleep_time}s..."
              sleep $sleep_time
              attempt=$((attempt+1))
            done
          }

          retry_command apt-get update
          retry_command apt-get install -y ufw

          retry_command sh -c 'curl -fsSL https://tailscale.com/install.sh | sh'

          echo 'net.ipv4.ip_forward = 1' | tee -a /etc/sysctl.d/99-tailscale.conf
          echo 'net.ipv6.conf.all.forwarding = 1' | tee -a /etc/sysctl.d/99-tailscale.conf
          sysctl -p /etc/sysctl.d/99-tailscale.conf

          retry_command tailscale up --authkey=${var.tailscale_auth_key} --ssh --accept-dns=false --advertise-routes=10.0.0.0/16

          timeout 60s bash -c 'until ip link show tailscale0; do sleep 1; done'

          ufw allow in on tailscale0 to any port 22 comment 'Permitir SSH via Tailscale'
          ufw deny 22/tcp comment 'Bloquear SSH publico'
          ufw --force enable
      EOF
    )
  }
}
