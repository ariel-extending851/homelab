# Ansible Automation for Homelab Hybrid Cluster

This directory contains Ansible roles, playbooks, and inventory scripts for automating the configuration and deployment of the k3s hybrid cluster (Oracle Cloud + Raspberry Pi).

## Directory Structure

```
ansible/
├── README.md                    # This file
├── terraform_inventory.py       # Dynamic inventory script (Terraform → Ansible)
└── roles/
    └── k3s/                     # k3s installation and configuration role
        ├── handlers/
        └── templates/
```

## Dynamic Inventory

### Overview

The `terraform_inventory.py` script is an **Ansible Dynamic Inventory** plugin that reads the Terraform state from `../infra/oci/` and generates a real-time inventory of k3s nodes.

**Benefits:**
- No manual IP address management (eliminates `hosts.ini` maintenance)
- Single source of truth (Terraform state)
- Automatically assigns roles: first node = `k3s_server`, others = `k3s_agent`
- Includes metadata (private IPs, public IPs, node indices)

### Usage

#### List all hosts
```bash
./terraform_inventory.py --list
```

#### Get variables for a specific host
```bash
./terraform_inventory.py --host hl-k3s-node-0
```

#### Use with Ansible commands
```bash
# Ping all hosts
ansible all -i terraform_inventory.py -m ping

# Check k3s server status
ansible k3s_server -i terraform_inventory.py -m shell -a "systemctl status k3s"

# List k3s agents
ansible-inventory -i terraform_inventory.py --graph
```

#### Run a playbook
```bash
ansible-playbook -i terraform_inventory.py playbooks/deploy_k3s.yml
```

### Inventory Structure

The dynamic inventory organizes hosts into the following groups:

```
@all
  ├── @k3s_cluster
  │   ├── @k3s_server     # First Terraform-managed node (control plane)
  │   │   └── hl-k3s-node-0
  │   └── @k3s_agent      # Remaining Terraform-managed nodes
  │       └── hl-k3s-node-1
```

### Host Variables

Each host includes the following variables (accessible via `hostvars`):

| Variable        | Description                                    | Example            |
|-----------------|------------------------------------------------|--------------------|
| `ansible_host`  | Public IP address (used for SSH connections)   | `144.22.184.6`     |
| `ansible_user`  | SSH user (OCI default: `opc`)                  | `opc`              |
| `public_ip`     | Public IP address                              | `144.22.184.6`     |
| `private_ip`    | Private VCN IP address                         | `10.0.1.7`         |
| `node_index`    | Node index in Terraform array (0-based)        | `0`                |

### Requirements

- **Terraform CLI** installed and in `$PATH`
- Terraform state initialized in `../infra/oci/`
- Python 3.6+

### Troubleshooting

#### Error: "Terraform state not found"
```
ERROR: Terraform state not found at ../infra/oci/terraform.tfstate
```

**Solution:** Ensure you have run `terraform apply` in the `infra/oci/` directory.

#### Error: "Missing required Terraform outputs"
```
ERROR: Missing required Terraform outputs (k3s_node_names, k3s_node_public_ips, k3s_node_private_ips)
```

**Solution:** Verify that `infra/oci/outputs.tf` defines the required outputs:
- `k3s_node_names`
- `k3s_node_public_ips`
- `k3s_node_private_ips`

Run `terraform apply` to regenerate outputs if modified.

## AWS DOP-C02 Exam Parallel

**Concept:** Dynamic Inventory  
**AWS Equivalent:** AWS Systems Manager (SSM) Dynamic Inventory + EC2 Tag-based Filtering

In AWS, you would use:
- **SSM Inventory:** Automatically collects metadata from EC2 instances
- **EC2 Tags:** Group instances by role (e.g., `Role=K8sControlPlane`, `Role=K8sWorker`)
- **Ansible AWS EC2 Plugin:** Native dynamic inventory for AWS (`amazon.aws.aws_ec2`)

Example AWS dynamic inventory configuration:
```yaml
# aws_ec2.yml (Ansible AWS EC2 plugin)
plugin: amazon.aws.aws_ec2
regions:
  - us-west-2
filters:
  tag:Environment: production
  tag:Project: homelab
keyed_groups:
  - key: tags.Role
    prefix: k8s
```

This would create groups like `k8s_ControlPlane` and `k8s_Worker` automatically.

**Exam Tip (DOP-C02):** For multi-cloud or hybrid scenarios, AWS Systems Manager can manage both EC2 and on-premises instances via SSM Agent. This is similar to our Tailscale mesh approach for the hybrid cluster.

## Next Steps

1. **Phase 2 Tasks (Pending):**
   - Create k3s installation playbook
   - Implement server/agent join logic
   - Extract kubeconfig from server node

2. **Future Enhancements:**
   - Add Raspberry Pi nodes to inventory (via static section or Tailscale API)
   - Implement Ansible Vault for SSH key management
   - Create CI/CD pipeline for Ansible linting (ansible-lint)
