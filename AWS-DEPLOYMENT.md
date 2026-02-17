# AWS Homelab - Complete Deployment Guide

**Purpose:** Deploy complete AWS infrastructure + k3s cluster + ArgoCD + applications with a single command.

---

## 🎯 What This Does

Running the deployment script will:

1. **Create AWS Infrastructure** (Terraform)
   - VPC, Security Groups, IAM roles
   - 2x EC2 Spot instances (t3.medium + t3.small)
   - Lambda scheduler (auto start/stop 10 AM - 9 PM BRT)

2. **Wait for Instances**
   - Wait for EC2 instances to boot
   - Wait for SSH to be available
   - Verify Tailscale connection

3. **Configure Kubernetes** (Ansible)
   - Deploy k3s cluster
   - Optimize nodes
   - Install ArgoCD with SOPS
   - Bootstrap all applications

4. **Verify Deployment**
   - Retrieve kubeconfig
   - Check cluster health
   - Display access instructions

**Total time:** 15-25 minutes (unattended)

---

## 📋 Prerequisites

### 1. Install Required Tools

```bash
# Terraform (if not installed)
# macOS:
brew install terraform

# Ubuntu/Debian:
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update && sudo apt install terraform

# Ansible (if not installed)
pip3 install ansible

# Verify installations
terraform --version  # Should be >= 1.0
ansible --version    # Should be >= 2.10
```

### 2. Install Ansible Collections

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml

# Verify
ansible-galaxy collection list | grep -E "(kubernetes|sops)"
```

### 3. Install Python Dependencies

```bash
# Kubernetes Python library
pip3 install kubernetes

# Verify
python3 -c "import kubernetes; print('OK')"
```

### 4. AWS Credentials

```bash
# Configure AWS CLI
aws configure

# Or set environment variables
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_DEFAULT_REGION="us-east-1"

# Verify
aws sts get-caller-identity
```

### 5. SSH Key

```bash
# Generate SSH key for EC2 instances
ssh-keygen -t ed25519 -f ~/.ssh/homelab-aws -C "homelab-ec2" -N ""

# Key should exist at:
ls ~/.ssh/homelab-aws
```

### 6. SOPS Age Key

```bash
# Should already exist from Phase 2
ls ~/.config/sops/age/keys.txt

# If not, see ansible/PHASE2-SETUP.md for instructions
```

### 7. GitHub Deploy Key

```bash
# Should already exist from Phase 2
ls ~/.ssh/homelab-deploy-key

# If not, see ansible/PHASE2-SETUP.md for instructions
```

---

## 🚀 Quick Start

### Option 1: Using the Deployment Script (Recommended)

```bash
# Make script executable (first time only)
chmod +x bin/deploy-aws-homelab.sh

# Deploy everything
./bin/deploy-aws-homelab.sh
```

### Option 2: Using Makefile

```bash
# Deploy everything
make deploy

# Show all available commands
make help
```

### Option 3: Manual Steps (Educational)

```bash
# Step 1: Create AWS infrastructure
cd infra/aws
terraform init
terraform apply -auto-approve

# Step 2: Wait for instances (get IPs)
SERVER_IP=$(terraform output -raw k3s_server_public_ip)
until ssh -i ~/.ssh/homelab-aws ec2-user@$SERVER_IP "echo ready"; do
    sleep 10
done

# Step 3: Configure k3s cluster
cd ../../ansible
ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml

# Step 4: Get kubeconfig
ssh -i ~/.ssh/homelab-aws ec2-user@$SERVER_IP \
    "sudo cat /etc/rancher/k3s/k3s.yaml" | \
    sed "s|127.0.0.1|$SERVER_IP|g" > ~/.kube/homelab-config

export KUBECONFIG=~/.kube/homelab-config
kubectl get nodes
```

---

## 📊 What Happens During Deployment

### Phase 1: Terraform (3-5 minutes)

```
[INFO] Checking prerequisites...
[INFO] Initializing Terraform...
[INFO] Validating Terraform configuration...
[INFO] Applying Terraform configuration...

Creating resources:
  ✓ VPC and subnets
  ✓ Security groups
  ✓ IAM roles and policies
  ✓ EC2 Fleet (2x Spot instances)
  ✓ Lambda scheduler
  ✓ EventBridge rules

[SUCCESS] AWS infrastructure created
```

### Phase 2: Wait for Instances (2-5 minutes)

```
[INFO] Retrieving instance IPs from Terraform...
[INFO] k3s-server: 54.123.45.67
[INFO] k3s-agent:  54.123.45.68

[INFO] Waiting for SSH on 54.123.45.67...
[SUCCESS] SSH ready on 54.123.45.67
[INFO] Waiting for SSH on 54.123.45.68...
[SUCCESS] SSH ready on 54.123.45.68

[SUCCESS] All instances are ready
```

### Phase 3: Ansible Configuration (10-18 minutes)

```
[INFO] Running Ansible playbook...

PLAY [Phase 1.1 - Optimize Raspberry Pi Nodes] (skipped - AWS only)
PLAY [Phase 1.2 - Deploy k3s Cluster]
  ✓ Install k3s server on k3s-server-1
  ✓ Retrieve k3s token
  ✓ Install k3s agent on k3s-agent-2
  ✓ Verify cluster (2 nodes Ready)

PLAY [Phase 2.1 - Deploy ArgoCD]
  ✓ Install ArgoCD v2.13.2
  ✓ Configure SOPS plugin
  ✓ Set up Git repository
  ✓ Verify installation

PLAY [Phase 2.2 - Bootstrap Applications]
  ✓ Apply apps-root Application
  ✓ Wait for initial sync
  ✓ Monitor critical apps

PLAY [Phase 3 - Final Verification]
  ✓ Check cluster nodes
  ✓ Check applications
  ✓ Check pods

[SUCCESS] Kubernetes cluster configured
```

### Phase 4: Verification & Summary (1 minute)

```
[INFO] Retrieving kubeconfig...
[SUCCESS] Kubeconfig saved to /tmp/k3s-homelab-kubeconfig.yaml

╔════════════════════════════════════════════════════════════════╗
║              DEPLOYMENT COMPLETED SUCCESSFULLY!                ║
╚════════════════════════════════════════════════════════════════╝

Instance Information:
  k3s-server: 54.123.45.67
  k3s-agent:  54.123.45.68

Access Kubernetes:
  export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml
  kubectl get nodes

Access ArgoCD:
  kubectl port-forward svc/argocd-server -n argocd 8080:443
  URL: https://localhost:8080
  Username: admin
  Password: <shown here>

Monitor Applications:
  kubectl get applications -n argocd
  kubectl get pods -A
```

---

## 🔍 Verification

### 1. Check Kubernetes Nodes

```bash
export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml
kubectl get nodes -o wide

# Expected output (2 AWS nodes + 2 RPi nodes if connected):
# NAME            STATUS   ROLES                  AGE   VERSION
# k3s-server-1    Ready    control-plane,master   5m    v1.34.3+k3s1
# k3s-agent-2     Ready    <none>                 4m    v1.34.3+k3s1
# rasp-pi-03      Ready    <none>                 2h    v1.34.3+k3s1
# rasp-pi-04      Ready    <none>                 2h    v1.34.3+k3s1
```

### 2. Check ArgoCD

```bash
# Check ArgoCD pods
kubectl get pods -n argocd

# Expected: All Running, repo-server should show 2/2 (main + SOPS sidecar)

# Check applications
kubectl get applications -n argocd

# Expected: apps-root and all child apps (***, ***, etc.)
```

### 3. Access ArgoCD UI

```bash
# Get admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d && echo

# Port forward
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Open browser: https://localhost:8080
# Username: admin
# Password: <from above>
```

### 4. Check Applications

```bash
# List all pods
kubectl get pods -A -o wide

# Check media namespace
kubectl get pods -n media

# Check Tailscale ingresses
kubectl get ingress -A

# Test app access (if Tailscale configured)
curl -I https://***.tail57bf10.ts.net
```

---

## 🛠️ Makefile Commands

```bash
# Show all available commands
make help

# Deployment
make deploy              # Full deployment
make destroy             # Destroy infrastructure

# Terraform
make terraform-plan      # Show planned changes
make terraform-apply     # Apply infrastructure only
make terraform-output    # Show outputs

# Ansible
make ansible-deploy      # Run Ansible only
make ansible-ping        # Test connectivity
make ansible-health      # Health check

# Kubernetes
make k8s-nodes           # Show nodes
make k8s-pods            # Show all pods
make k8s-apps            # Show ArgoCD apps
make k8s-kubeconfig      # Download kubeconfig
make argocd-password     # Get admin password
make argocd-port-forward # Port forward ArgoCD

# Status
make status              # Overall status
make test                # Run all tests
```

---

## 🔄 Common Scenarios

### Scenario 1: First-Time Deployment

```bash
# Deploy everything
./bin/deploy-aws-homelab.sh

# Or with make
make deploy
```

### Scenario 2: Instances Were Terminated

```bash
# Same command recreates everything
./bin/deploy-aws-homelab.sh

# Infrastructure will be recreated with new IPs
# Ansible will configure the new instances
# ArgoCD will sync applications
```

### Scenario 3: Just Update Configuration (Infrastructure Exists)

```bash
# Run Ansible only
make ansible-deploy

# Or directly
cd ansible
ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml
```

### Scenario 4: Destroy Everything

```bash
# Interactive destruction
make destroy

# Or with script
./bin/deploy-aws-homelab.sh --destroy
```

### Scenario 5: Check Status Without Making Changes

```bash
# Overall status
make status

# Terraform plan (see what would change)
make terraform-plan

# Ansible check mode (dry run)
make ansible-check
```

---

## ⚠️ Troubleshooting

### Issue 1: "Terraform not found"

```bash
# Install Terraform
brew install terraform  # macOS
# Or follow: https://www.terraform.io/downloads
```

### Issue 2: "SSH connection timeout"

```bash
# Check security group allows SSH from your IP
cd infra/aws
terraform output

# Verify SSH key exists
ls ~/.ssh/homelab-aws

# Test SSH manually
SERVER_IP=$(cd infra/aws && terraform output -raw k3s_server_public_ip)
ssh -i ~/.ssh/homelab-aws ec2-user@$SERVER_IP
```

### Issue 3: "Ansible playbook failed"

```bash
# Check Ansible can reach instances
cd ansible
ansible all -i terraform_inventory_aws.py -m ping

# Check dynamic inventory
python3 terraform_inventory_aws.py --list

# Run with verbose output
ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml -vvv
```

### Issue 4: "ArgoCD apps stuck in Progressing"

```bash
# Check ArgoCD logs
kubectl logs -n argocd deployment/argocd-application-controller

# Check repo-server logs (SOPS issues)
kubectl logs -n argocd deployment/argocd-repo-server -c sops-plugin

# Force sync
kubectl patch application <app-name> -n argocd \
  --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

### Issue 5: "EC2 instances keep getting terminated"

```bash
# Check spot instance settings
cd infra/aws
terraform show | grep spot

# Spot instances can be interrupted by AWS
# The scheduler will restart them (10 AM - 9 PM BRT)
# Or run deployment script to recreate
```

### Issue 6: "Deployment script fails mid-way"

```bash
# Script is safe to re-run (idempotent)
./bin/deploy-aws-homelab.sh

# If Terraform already applied, it will show "no changes"
# If Ansible already configured, it will skip completed tasks
```

---

## 💰 Cost Breakdown

**Monthly Costs (with scheduler running 11 hours/day):**

| Resource | Hours/Month | Cost/Hour | Monthly Cost |
|----------|-------------|-----------|--------------|
| t3.medium spot | 330 | $0.0187 | $6.17 |
| t3.small spot | 330 | $0.0094 | $3.10 |
| EBS 20GB gp3 (server) | 720 | - | $1.60 |
| EBS 20GB gp3 (agent) | 720 | - | $1.60 |
| Lambda executions | ~60/month | Free tier | $0.00 |
| Data transfer | ~10GB | $0.09/GB | $0.90 |
| **TOTAL** | - | - | **~$13.37/month** |

**If running 24/7:**
- t3.medium: $13.46/month
- t3.small: $6.77/month
- Storage + other: $4.10/month
- **Total: ~$24.33/month**

**Savings with scheduler:** ~45% ($10.96/month saved)

---

## 🔐 Security Considerations

### SSH Keys
- EC2 SSH key: `~/.ssh/homelab-aws`
- GitHub deploy key: `~/.ssh/homelab-deploy-key`
- **Never commit private keys to Git**

### SOPS Age Key
- Located: `~/.config/sops/age/keys.txt`
- Used by ArgoCD to decrypt secrets
- **Keep backup in secure location**

### AWS Credentials
- Stored in `~/.aws/credentials`
- Or use environment variables (better for CI/CD)
- **Use IAM user with least privilege**

### ArgoCD Admin Password
- Auto-generated on first install
- Stored in: `argocd-initial-admin-secret`
- **Change password after first login**

---

## 📚 Additional Resources

- **Main README:** `README.md`
- **Ansible Documentation:** `ansible/README.md`
- **Phase 2 Setup:** `ansible/PHASE2-SETUP.md`
- **Testing Guide:** `ansible/TESTING.md`
- **Terraform AWS:** `infra/aws/README.md`

---

## 🎯 Summary

**Can you recreate everything without CLI?**

✅ **YES!** Just run:
```bash
./bin/deploy-aws-homelab.sh
```

**What if instances are terminated?**

✅ **Same command recreates everything:**
- Terraform creates new instances
- Ansible configures them
- ArgoCD syncs apps
- Zero manual intervention

**Total time:** 15-25 minutes, fully automated

**Cost:** ~$13/month (with 11h/day schedule)

---

**Questions? Issues? Check the troubleshooting section or open a GitHub issue!** 🚀
