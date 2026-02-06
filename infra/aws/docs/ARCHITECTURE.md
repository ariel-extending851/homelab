# AWS Infrastructure Architecture

## 📂 Modular Structure

This project follows Terraform best practices with a modular architecture, similar to the OCI infrastructure.

### Structure Comparison

#### Before (Monolithic)
```
aws/
├── main.tf                    # Everything in one file
├── variables.tf
├── outputs.tf
├── user-data.sh.tpl
└── terraform.tfvars.sops.yaml
```

#### After (Modular) ✅
```
aws/
├── modules/                   # Reusable modules
│   ├── compute/              # EC2, IAM, SSH
│   │   ├── templates/
│   │   │   └── user_data.tftpl
│   │   ├── main.tf
│   │   ├── outputs.tf
│   │   └── variables.tf
│   └── network/              # VPC, Security Groups
│       ├── main.tf
│       ├── outputs.tf
│       ├── variables.tf
│       └── versions.tf
├── main.tf                   # Root orchestration
├── variables.tf              # Root variables
├── outputs.tf                # Root outputs
└── terraform.tfvars.sops.yaml
```

---

## 🏗️ Module Design

### Network Module (`modules/network/`)

**Purpose:** Manages all networking resources for the k3s cluster.

**Resources:**
- ✅ Default VPC data source (cost optimization)
- ✅ Default subnets (multi-AZ spot flexibility)
- ✅ Security group (k3s + PostgreSQL + SSH)

**Inputs:**
```hcl
variable "ssh_allowed_cidr"     # CIDR blocks for SSH access
variable "k3s_api_allowed_cidr" # CIDR blocks for k3s API
```

**Outputs:**
```hcl
output "vpc_id"              # VPC ID
output "security_group_id"   # Security group for EC2 instances
output "subnet_ids"          # List of available subnets
```

**Why Default VPC?**
- ❌ Creating new VPC = $32/month (NAT Gateway)
- ✅ Using default VPC = $0/month
- ✅ Sufficient for homelab use case

---

### Compute Module (`modules/compute/`)

**Purpose:** Manages all compute resources for k3s nodes.

**Resources:**
- ✅ IAM role + instance profile (SSM Session Manager)
- ✅ SSH key pair (from SOPS-encrypted secret)
- ✅ Launch template (AMI, instance type, user data)
- ✅ EC2 Spot Instance requests (persistent)
- ✅ EC2 instance tags

**Inputs:**
```hcl
variable "instance_type"      # t3.small (default)
variable "ebs_volume_size"    # 20GB (default)
variable "spot_max_price"     # Empty = on-demand price
variable "ssh_key_name"       # Key pair name
variable "ssh_public_key"     # From SOPS
variable "security_group_id"  # From network module
variable "k3s_token"          # From SOPS
variable "k3s_version"        # k3s version to install
```

**Outputs:**
```hcl
output "k3s_server_public_ip"   # Server public IP
output "k3s_server_private_ip"  # Server private IP
output "k3s_agent_public_ip"    # Agent public IP
output "k3s_agent_private_ip"   # Agent private IP
output "k3s_server_instance_id" # EC2 instance ID
output "k3s_agent_instance_id"  # EC2 instance ID
output "iam_role_arn"           # IAM role ARN
```

**User Data Template:**
- Located at: `modules/compute/templates/user_data.tftpl`
- Installs k3s server on node 1
- Installs k3s agent on node 2
- Installs CloudNativePG operator on server

---

## 🔄 Data Flow

```
┌─────────────────────────────────────────────────────────┐
│  Root Module (main.tf)                                  │
│                                                          │
│  1. Loads SOPS secrets                                  │
│     ├─ ssh_public_key                                   │
│     └─ k3s_token                                        │
│                                                          │
│  2. Instantiates Network Module                         │
│     └─▶ Creates VPC, Security Groups                   │
│         └─ Outputs: security_group_id                   │
│                                                          │
│  3. Instantiates Compute Module                         │
│     ├─ Receives: security_group_id from network         │
│     ├─ Receives: ssh_public_key from SOPS               │
│     ├─ Receives: k3s_token from SOPS                    │
│     └─▶ Creates EC2 instances                          │
│         └─ Outputs: IPs, instance IDs                   │
│                                                          │
│  4. Exposes outputs to user                             │
│     └─ SSH commands, kubeconfig commands                │
└─────────────────────────────────────────────────────────┘
```

---

## 🎯 Design Principles

### 1. **Separation of Concerns**
- Network module handles networking
- Compute module handles instances
- Root module orchestrates everything

### 2. **DRY (Don't Repeat Yourself)**
- User data template reused for both nodes
- Security group rules defined once
- Variables validated at module level

### 3. **Security by Default**
- SOPS encryption for secrets
- IMDSv2 enforced
- EBS encryption enabled
- Least privilege IAM roles

### 4. **Cost Optimization**
- Default VPC (no NAT Gateway costs)
- Spot instances (59% discount)
- gp3 storage (cheaper than gp2)
- Single-AZ deployment (lab use case)

### 5. **Maintainability**
- Clear module boundaries
- Well-documented inputs/outputs
- Terraform fmt compliant
- Follows OCI infrastructure pattern

---

## 📊 Resource Inventory

| Module | Resource Type | Count | Purpose |
|--------|--------------|-------|---------|
| **network** | VPC Data Source | 1 | Default VPC |
| **network** | Subnet Data Source | N | Available subnets |
| **network** | Security Group | 1 | k3s cluster |
| **compute** | IAM Role | 1 | EC2 instance role |
| **compute** | IAM Policy Attachment | 1 | SSM Session Manager |
| **compute** | IAM Instance Profile | 1 | Attach role to instances |
| **compute** | SSH Key Pair | 1 | SSH access |
| **compute** | Launch Template | 1 | EC2 configuration |
| **compute** | Spot Instance Request | 2 | k3s server + agent |
| **compute** | EC2 Tag | 2 | Instance naming |
| **TOTAL** | | **13** | |

---

## 🔐 Security Architecture

### Secrets Management (SOPS)
```
terraform.tfvars.sops.yaml (ENCRYPTED)
    ├─ ssh_public_key  ──▶  modules/compute/aws_key_pair
    └─ k3s_token       ──▶  modules/compute/user_data template
```

### IAM Permissions (Least Privilege)
```
k3s-node-role
  └─ AmazonSSMManagedInstanceCore (AWS managed policy)
     ├─ ssm:UpdateInstanceInformation
     ├─ ssmmessages:CreateControlChannel
     ├─ ssmmessages:CreateDataChannel
     ├─ ssmmessages:OpenControlChannel
     └─ ssmmessages:OpenDataChannel
```

### Network Security
```
Security Group: k3s-cluster-sg
  Ingress:
    ├─ 22/tcp     from var.ssh_allowed_cidr
    ├─ 6443/tcp   from var.k3s_api_allowed_cidr
    ├─ 10250/tcp  from self (kubelet)
    ├─ 8472/udp   from self (flannel VXLAN)
    ├─ 5432/tcp   from self (PostgreSQL)
    └─ all        from self (cluster communication)

  Egress:
    └─ all/all    to 0.0.0.0/0 (internet access)
```

---

## 🚀 Deployment Flow

### Step 1: Module Initialization
```bash
terraform init
# Downloads providers: aws, sops
# Initializes modules: network, compute
```

### Step 2: Planning
```bash
terraform plan
# Decrypts SOPS secrets
# Plans 13 resources across 2 modules
```

### Step 3: Apply
```bash
terraform apply
# Creates resources in order:
#   1. network module (VPC, SG)
#   2. compute module (IAM, SSH key)
#   3. compute module (spot instances)
```

### Step 4: User Data Execution (on EC2)
```
EC2 Instance Boot
  └─ Cloud-Init executes user_data
     ├─ System updates (dnf update)
     ├─ Install packages (git, jq, htop)
     ├─ Configure kernel modules (overlay, br_netfilter)
     ├─ Configure sysctl (ip forwarding)
     └─ Install k3s
        ├─ Server: k3s install --disable traefik
        │   └─ Install CloudNativePG operator
        └─ Agent: k3s agent --server https://SERVER_IP:6443
```

---

## 📈 Scaling Considerations

### Current Architecture (2 nodes)
- ✅ 1× Control plane (k3s server)
- ✅ 1× Worker node (k3s agent)
- ✅ Cost: ~$17.65/month

### Scaling to 3+ nodes
To add more nodes, modify `modules/compute/main.tf`:

```hcl
# Option 1: Add individual spot requests
resource "aws_spot_instance_request" "k3s_agent_2" {
  # Same config as k3s_agent
}

# Option 2: Use count (better for many nodes)
resource "aws_spot_instance_request" "k3s_agents" {
  count = var.agent_count
  # Use count.index in user_data
}
```

**Cost per additional node:** ~$7.83/month (t3.small spot + 20GB gp3)

---

## 🛠️ Module Reusability

### Using These Modules in Other Projects

```hcl
# Example: Different region/configuration
module "k3s_us_west" {
  source = "git::https://github.com/your-org/homelab//infra/aws/modules/compute"

  instance_type     = "t3.medium"
  security_group_id = module.network_us_west.security_group_id
  ssh_public_key    = var.ssh_key
  k3s_token         = var.k3s_token
  k3s_version       = "v1.29.0+k3s1"
}
```

---

## 🎓 Why This Architecture?

### ✅ **Tech Lead Approved**

1. **Modularity**: Easy to test, modify, and reuse
2. **Consistency**: Matches OCI infrastructure pattern
3. **Security**: Secrets management built-in
4. **Cost**: Optimized for homelab budget
5. **Maintainability**: Clear separation of concerns
6. **Scalability**: Easy to add more nodes/regions

### 📚 Follows Best Practices

- [x] Terraform Module Structure (HashiCorp)
- [x] AWS Well-Architected Framework
- [x] Infrastructure as Code patterns
- [x] GitOps-ready (SOPS encrypted secrets)
- [x] DOP-C02 (AWS DevOps Professional) principles

---

## 📖 Related Documentation

- [README.md](./README.md) - Full setup guide
- [QUICKSTART.md](./QUICKSTART.md) - 5-minute deployment
- [SOPS_SETUP.md](./SOPS_SETUP.md) - Secrets management

---

**Architecture Version:** 2.0 (Modular)
**Last Updated:** 2026-02-04
**Maintainer:** Tech Lead
