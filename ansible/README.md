# Ansible Automation for Homelab Hybrid Cluster

This directory contains Ansible roles, playbooks, and inventory scripts for automating the configuration and deployment of the k3s hybrid cluster (Oracle Cloud + AWS + Raspberry Pi).

## Directory Structure

```
ansible/
├── README.md                       # This file
├── terraform_inventory.py          # Dynamic inventory for OCI (Oracle Cloud)
├── terraform_inventory_aws.py      # Dynamic inventory for AWS
└── roles/
    └── k3s/                        # k3s installation and configuration role
        ├── defaults/
        ├── handlers/
        ├── tasks/
        └── templates/
```

## Dynamic Inventory

### Overview

We provide **two dynamic inventory scripts** for different cloud providers:

| Script | Cloud Provider | SSH User | Directory |
|--------|---------------|----------|-----------|
| `terraform_inventory.py` | Oracle Cloud (OCI) | `opc` | `../infra/oci/` |
| `terraform_inventory_aws.py` | AWS | `ec2-user` | `../infra/aws/` |

**Benefits:**
- No manual IP address management (eliminates `hosts.ini` maintenance)
- Single source of truth (Terraform state)
- Automatically assigns roles: server = `k3s_server`, agent = `k3s_agent`
- Includes metadata (private IPs, public IPs, instance IDs)

---

## AWS Dynamic Inventory

### Usage

#### List all hosts
```bash
./terraform_inventory_aws.py --list
```

#### Get variables for a specific host
```bash
./terraform_inventory_aws.py --host k3s-server
```

#### Test connectivity
```bash
# Ping all hosts
ansible all -i terraform_inventory_aws.py -m ping

# Check server status
ansible k3s_server -i terraform_inventory_aws.py -m shell -a "uptime"

# View inventory graph
ansible-inventory -i terraform_inventory_aws.py --graph
```

#### Deploy k3s cluster
```bash
ansible-playbook -i terraform_inventory_aws.py playbooks/deploy_k3s.yml
```

### Inventory Structure (AWS)

The dynamic inventory organizes hosts into the following groups:

```
@all
  ├── @k3s_cluster
  │   ├── @k3s_server     # Control plane node
  │   │   └── k3s-server
  │   └── @k3s_agent      # Worker node
  │       └── k3s-agent
```

### Host Variables (AWS)

Each host includes the following variables (accessible via `hostvars`):

| Variable | Description | Example |
|----------|-------------|---------|
| `ansible_host` | Public IP address | `54.214.0.159` |
| `ansible_user` | SSH user (AWS: `ec2-user`) | `ec2-user` |
| `public_ip` | Public IP address | `54.214.0.159` |
| `private_ip` | Private subnet IP | `10.47.20.188` |
| `instance_id` | EC2 instance ID | `i-1bab870d9e7aa7625` |
| `node_type` | Node role | `server` or `agent` |
| `k3s_control_node` | Is control plane? | `true` or `false` |

### Requirements (AWS)

- **Terraform CLI** installed and in `$PATH`
- Terraform state initialized in `../infra/aws/`
- AWS infrastructure deployed (`terraform apply` completed)
- Python 3.6+
- SSH key at `~/.ssh/homelab-aws` (or as configured)

---

## OCI Dynamic Inventory

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

### Inventory Structure (OCI)

```
@all
  ├── @k3s_cluster
  │   ├── @k3s_server     # First Terraform-managed node (control plane)
  │   │   └── hl-k3s-node-0
  │   └── @k3s_agent      # Remaining Terraform-managed nodes
  │       └── hl-k3s-node-1
```

### Host Variables (OCI)

| Variable | Description | Example |
|----------|-------------|---------|
| `ansible_host` | Public IP address | `144.22.184.6` |
| `ansible_user` | SSH user (OCI: `opc`) | `opc` |
| `public_ip` | Public IP address | `144.22.184.6` |
| `private_ip` | Private VCN IP | `10.0.1.7` |
| `node_index` | Node index (0-based) | `0` |

### Requirements (OCI)

- **Terraform CLI** installed and in `$PATH`
- Terraform state initialized in `../infra/oci/`
- Python 3.6+

---

## Troubleshooting

### Error: "Failed to read Terraform outputs"

```
ERROR: Failed to read Terraform outputs: ...
```

**Solution:**
- Ensure you're in the correct directory (`ansible/`)
- Verify `terraform apply` has been run in the corresponding infra directory
- Check that `../infra/aws/` or `../infra/oci/` exists

### Error: "Missing required Terraform output"

```
ERROR: Missing required Terraform output (k3s_server_public_ip)
```

**Solution:**
- For AWS: Verify `infra/aws/outputs.tf` defines:
  - `k3s_server_public_ip`
  - `k3s_agent_public_ip`
- For OCI: Verify `infra/oci/outputs.tf` defines:
  - `k3s_node_names`
  - `k3s_node_public_ips`

Run `terraform apply` to regenerate outputs.

### Error: "SSH connection refused"

```
k3s-server | UNREACHABLE! => {"changed": false, "msg": "Failed to connect..."}
```

**Solution:**
- Ensure security groups allow SSH (port 22)
- Verify SSH key is correct: `~/.ssh/homelab-aws` for AWS
- Check instance is running: `terraform show` or AWS Console
- For AWS: First connection may need `StrictHostKeyChecking=no`

---

## Playbooks

### deploy_k3s.yml

Deploys a complete k3s cluster with server and agent nodes:

```bash
# Deploy entire cluster
ansible-playbook -i terraform_inventory_aws.py playbooks/deploy_k3s.yml

# Deploy only server
ansible-playbook -i terraform_inventory_aws.py playbooks/deploy_k3s.yml --tags server

# Deploy only agent
ansible-playbook -i terraform_inventory_aws.py playbooks/deploy_k3s.yml --tags agent
```

**What it does:**
1. Installs k3s server (control plane) on `k3s_server` host
2. Retrieves join token from server
3. Installs k3s agent on `k3s_agent` host
4. Verifies cluster is operational

---

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
  - us-east-1
filters:
  tag:Environment: production
  tag:Project: homelab
keyed_groups:
  - key: tags.Role
    prefix: k8s
```

This would create groups like `k8s_ControlPlane` and `k8s_Worker` automatically.

**Exam Tip (DOP-C02):** For multi-cloud or hybrid scenarios, AWS Systems Manager can manage both EC2 and on-premises instances via SSM Agent. This is similar to our Tailscale mesh approach for the hybrid cluster.

---

## Next Steps

1. **Deploy k3s on AWS:**
   ```bash
   cd ../infra/aws
   terraform apply
   cd ../../ansible
   ansible-playbook -i terraform_inventory_aws.py playbooks/deploy_k3s.yml
   ```

2. **Future Enhancements:**
   - Add Raspberry Pi nodes to inventory (via static section or Tailscale API)
   - Implement Ansible Vault for SSH key management
   - Create CI/CD pipeline for Ansible linting (ansible-lint)
   - Add monitoring and logging playbooks
   - Implement backup/restore playbooks for etcd

---

## Cost Optimization Notes

**AWS Setup (~$15.61/month):**
- 2× t3.small spot instances: ~$12.41/month
- 40 GB gp3 EBS storage: ~$3.20/month
- CloudNativePG (PostgreSQL on k3s): $0

**Savings vs managed services:**
- RDS PostgreSQL (db.t3.micro): ~$15.44/month saved
- EKS cluster: ~$73/month saved
- **Total savings: ~$88/month (85% cheaper!)**
