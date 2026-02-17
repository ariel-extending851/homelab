# Homelab Quickstart - 5 Minutes to Deployment

**For the impatient:** Get your complete homelab running in one command.

---

## 🚀 Prerequisites (One-Time Setup)

```bash
# 1. Install tools
brew install terraform ansible  # macOS
# OR: pip3 install ansible && <install terraform>

# 2. Install Ansible collections
cd ansible && ansible-galaxy collection install -r requirements.yml

# 3. Install Python kubernetes library
pip3 install kubernetes

# 4. Configure AWS credentials
aws configure  # Or set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY

# 5. Generate SSH key
ssh-keygen -t ed25519 -f ~/.ssh/homelab-aws -N ""
```

---

## ⚡ Deploy Everything (One Command)

```bash
# Make script executable (first time only)
chmod +x bin/deploy-aws-homelab.sh

# Deploy complete infrastructure
./bin/deploy-aws-homelab.sh
```

**Or with Makefile:**
```bash
make deploy
```

**What happens:**
1. Creates AWS infrastructure (Terraform)
2. Waits for instances to boot
3. Configures k3s cluster (Ansible)
4. Installs ArgoCD with SOPS
5. Bootstraps all applications

**Time:** 15-25 minutes (unattended)

---

## ✅ Verify Deployment

```bash
# Set kubeconfig
export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml

# Check nodes (should show 2 AWS + 2 RPi if connected)
kubectl get nodes

# Check applications
kubectl get applications -n argocd

# Check all pods
kubectl get pods -A
```

---

## 🎯 Access ArgoCD

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

---

## 🔄 Common Operations

```bash
# Destroy infrastructure
make destroy
# OR: ./bin/deploy-aws-homelab.sh --destroy

# Recreate after termination (same command)
make deploy

# Check status
make status

# Update configuration only (infrastructure exists)
make ansible-deploy

# Health check
make ansible-health

# Show all commands
make help
```

---

## 💰 Cost

**With 11-hour daily schedule (10 AM - 9 PM BRT):**
- ~$13/month

**Running 24/7:**
- ~$24/month

**Scheduler automatically:**
- Starts instances: 10:00 AM BRT
- Stops instances: 21:00 PM BRT (9 PM)

---

## 📚 Full Documentation

- **Complete Guide:** `AWS-DEPLOYMENT.md`
- **Ansible Phase 2:** `ansible/PHASE2-SETUP.md`
- **Testing:** `ansible/TESTING.md`
- **Main README:** `README.md`

---

## ⚠️ Troubleshooting

### Deployment fails?
```bash
# Re-run (script is idempotent)
./bin/deploy-aws-homelab.sh
```

### Can't SSH to instances?
```bash
# Check security group allows your IP
cd infra/aws && terraform output

# Verify SSH key exists
ls ~/.ssh/homelab-aws
```

### ArgoCD apps stuck?
```bash
# Force sync all
kubectl get applications -n argocd -o name | \
  xargs -I {} kubectl patch {} -n argocd \
    --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

---

**That's it! Your homelab is running.** 🎉

For detailed documentation, see `AWS-DEPLOYMENT.md`
