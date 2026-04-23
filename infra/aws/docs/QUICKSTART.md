# AWS Homelab - Quick Start (5 Minutes)

**Architecture:** Modular Terraform (network + compute modules)

---

## 📂 What's Inside

```
aws/
├── modules/
│   ├── compute/     # EC2 spot instances, IAM, SSH
│   └── network/     # VPC, security groups
├── main.tf          # Root module
├── outputs.tf       # Instance IPs, commands
└── *.md            # Documentation
```

---

## 🚀 Setup in 6 Steps

### 1️⃣ Install Tools (1 min)

```bash
# macOS
brew install sops age terraform

# Linux
# See SOPS_SETUP.md for detailed instructions
```

### 2️⃣ Configure SOPS (2 min)

```bash
# Generate AGE encryption key
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt

# Get your public key (save this!)
grep "# public key:" ~/.config/sops/age/keys.txt
# Example output: age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja

# Set environment variable (add to ~/.bashrc or ~/.zshrc)
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
```

### 3️⃣ Generate Secrets (1 min)

```bash
cd /var/mnt/nvme/repos/repos/homelab/infra/aws

# Generate SSH key
ssh-keygen -t ed25519 -C "homelab-aws" -f ~/.ssh/homelab-aws

# Generate k3s token
openssl rand -base64 32
```

### 4️⃣ Configure & Encrypt (1 min)

```bash
# Edit secrets file
nano terraform.tfvars.sops.yaml

# Add your values:
# - ssh_public_key: (content of ~/.ssh/homelab-aws.pub)
# - k3s_token: (output from openssl command above)

# Encrypt with SOPS (replace YOUR_AGE_PUBLIC_KEY)
sops --encrypt \
  --age YOUR_AGE_PUBLIC_KEY \
  --encrypted-regex '^(ssh_public_key|k3s_token)$' \
  terraform.tfvars.sops.yaml > terraform.tfvars.sops.yaml.enc

mv terraform.tfvars.sops.yaml.enc terraform.tfvars.sops.yaml

# Verify encryption
cat terraform.tfvars.sops.yaml | head -3
# Should see: ENC[AES256_GCM,data:...]
```

**Optional - Restrict Access to Your IP:**
```bash
# Get your public IP
curl -4 ifconfig.me

# Create terraform.tfvars
cat > terraform.tfvars <<EOF
ssh_allowed_cidr     = ["$(curl -4 -s ifconfig.me)/32"]
k3s_api_allowed_cidr = ["$(curl -4 -s ifconfig.me)/32"]
EOF
```

### 5️⃣ Configure AWS Credentials (2 min)

#### Option A: Using Mise (Recommended)

If you're using mise (configured in `.mise.toml`):

```bash
# Configure AWS profile (one-time setup)
aws configure --profile homelab
# Enter your AWS Access Key ID
# Enter your AWS Secret Access Key
# Region: us-east-1
# Output format: json

# The AWS_PROFILE environment variable is automatically set by mise
# when you enter the project directory
```

#### Option B: Manual Configuration

```bash
# Set environment variables
export AWS_PROFILE=homelab
export AWS_DEFAULT_REGION=us-east-1

# Or configure AWS CLI
aws configure --profile homelab
```

**Verify AWS access:**
```bash
aws sts get-caller-identity --profile homelab
```

### 6️⃣ Deploy (5 min)

```bash
# Initialize Terraform
terraform init

# Review plan (should show 2 instances + security groups)
terraform plan

# Deploy!
terraform apply

# Get outputs
terraform output
```

---

## 📋 Post-Deployment Checklist

### ✅ Access Your Cluster

```bash
# SSH to server
ssh -i ~/.ssh/homelab-aws ec2-user@<SERVER_IP>

# Check k3s status
sudo kubectl get nodes
sudo kubectl get pods -A

# Exit SSH
exit
```

### ✅ Get Kubeconfig Locally

```bash
# Copy kubeconfig
scp -i ~/.ssh/homelab-aws \
  ec2-user@<SERVER_IP>:/etc/rancher/k3s/k3s.yaml \
  ~/.kube/config-homelab

# Update server IP in kubeconfig
sed -i 's/127.0.0.1/<SERVER_PUBLIC_IP>/g' ~/.kube/config-homelab

# Use it
export KUBECONFIG=~/.kube/config-homelab
kubectl get nodes
```


```bash
kubectl get pods -n cnpg-system
# Should see: cnpg-controller-manager-xxxx Running
```

---

## 🐘 Deploy PostgreSQL Database

Create a PostgreSQL cluster:

```bash
kubectl apply -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: homelab-db
spec:
  instances: 2
  imageName: ghcr.io/cloudnative-pg/postgresql:16.1

  storage:
    size: 10Gi

  resources:
    requests:
      memory: "512Mi"
      cpu: "500m"
    limits:
      memory: "1Gi"
      cpu: "1000m"

  postgresql:
    parameters:
      max_connections: "100"
      shared_buffers: "256MB"

  bootstrap:
    initdb:
      database: homelab
      owner: app
EOF
```

Check status:
```bash
# Wait for cluster to be ready (2-3 minutes)
kubectl get cluster homelab-db -w

# Get connection credentials
kubectl get secret homelab-db-app -o jsonpath='{.data.password}' | base64 -d

# Connect to PostgreSQL
kubectl exec -it homelab-db-1 -- psql -U app -d homelab
```

---

## 🎯 Common Operations

### View Encrypted Secrets
```bash
sops --decrypt terraform.tfvars.sops.yaml
```

### Edit Encrypted Secrets
```bash
sops terraform.tfvars.sops.yaml
# SOPS will decrypt, open editor, re-encrypt on save
```

### Update Infrastructure
```bash
# Make changes to .tf files
terraform plan
terraform apply
```

### Destroy Everything
```bash
terraform destroy
# Or use AWS Nuke: python3 scripts/clean_lab.py
```

### Check Spot Instance Status
```bash
# From AWS CLI
aws ec2 describe-spot-instance-requests \
  --filters "Name=tag:Project,Values=Lab-DevOps-Pro"
```

### Handle Spot Interruption
Spot instances give 2-minute warning. k3s automatically reschedules pods.

Monitor interruptions:
```bash
# SSH to instance and check metadata
curl http://169.254.169.254/latest/meta-data/spot/instance-action
```

---

## 📊 Cost Monitoring

```bash
# Use AWS Cost Explorer or CLI
aws ce get-cost-and-usage \
  --time-period Start=2026-02-01,End=2026-02-28 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --filter file://<(cat <<EOF
{
  "Tags": {
    "Key": "Project",
    "Values": ["Lab-DevOps-Pro"]
  }
}
EOF
)
```

Expected: ~$17.65/month ($15.65 EC2 + ~$2 EBS)

---

## 🆘 Troubleshooting

### Issue: "no SOPS data found"
**Solution:** File not encrypted. Run encryption step (Step 4).

### Issue: "terraform plan fails with decrypt error"
**Solution:**
```bash
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
terraform init
```

### Issue: "k3s agent not joining cluster"
**Solution:**
```bash
# SSH to agent node
ssh -i ~/.ssh/homelab-aws ec2-user@<AGENT_IP>

# Check logs
sudo journalctl -u k3s-agent -f

# Check user-data execution
sudo cat /var/log/user-data.log
```

### Issue: "Spot instance interrupted"
**Normal behavior.** k3s will reschedule pods. Check new instance:
```bash
terraform refresh
terraform output
```

---

## 📚 Full Documentation

- 📖 [README.md](./README.md) - Complete guide
- 🔐 [SOPS_SETUP.md](./SOPS_SETUP.md) - Detailed SOPS setup
- 🏗️ Architecture diagram in README.md

---

## 🎓 Tech Lead Notes

**Security Checklist Before Production:**
- [ ] Encrypted terraform.tfvars.sops.yaml with SOPS
- [ ] Restricted SSH/k3s API to your IP (not 0.0.0.0/0)
- [ ] AGE key backed up securely
- [ ] IMDSv2 enabled (✅ already configured)
- [ ] EBS encryption enabled (✅ already configured)
- [ ] AWS CloudTrail enabled for audit logs
- [ ] Cost alerts configured in AWS Budgets

**Never commit:**
- ❌ Unencrypted terraform.tfvars.sops.yaml
- ❌ Private SSH keys
- ❌ kubeconfig files
- ❌ .terraform.tfstate (contains secrets)

---

**Total Setup Time:** ~5 minutes
**Total Infrastructure Cost:** ~$17.65 USD/month
**Production-Ready:** ✅ Yes (with security checklist completed)
