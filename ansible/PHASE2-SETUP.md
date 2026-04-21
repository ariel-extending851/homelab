## # Phase 2 Setup Guide - ArgoCD & GitOps

**Purpose:** This guide helps you prepare for Phase 2 deployment (ArgoCD + Application Bootstrap).

---

## 📋 Prerequisites Checklist

Before running Phase 2, ensure you have:

### 1. ✅ Python Dependencies

```bash
# Install Python kubernetes library
pip3 install kubernetes

# Verify
python3 -c "import kubernetes; print('OK')"
```

### 2. ✅ Ansible Collections

```bash
# Install required collections
cd ansible
ansible-galaxy collection install -r requirements.yml

# Verify
ansible-galaxy collection list | grep -E "(kubernetes|sops)"

# Expected output:
# kubernetes.core          3.x.x
# community.sops           1.x.x
```

### 3. ✅ SOPS Age Key

**Check if you already have one:**
```bash
ls -la ~/.config/sops/age/keys.txt
```

**If not, generate new key:**
```bash
# Install age (if not already installed)
# Ubuntu/Debian:
sudo apt install age

# macOS:
brew install age

# Generate key
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt

# Extract public key
grep 'public key:' ~/.config/sops/age/keys.txt
```

**⚠️ IMPORTANT:** The public key in your generated file must match:
```
age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja
```

If it doesn't match, you'll need to either:
- Option A: Use the existing key (if you have backup)
- Option B: Re-encrypt all secrets with new key (advanced)

### 4. ✅ GitHub Deploy Key

**Purpose:** Allow ArgoCD to clone your private repository.

**Create SSH key:**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/homelab-deploy-key -C "argocd@homelab" -N ""
```

**Add to GitHub:**
1. Copy public key:
   ```bash
   cat ~/.ssh/homelab-deploy-key.pub
   ```

2. Go to: https://github.com/ariel-extending851/homelab/settings/keys

3. Click "Add deploy key"
   - Title: `ArgoCD Homelab`
   - Key: Paste the public key
   - ✅ Allow write access (optional, for future automation)

4. Click "Add key"

**Test access:**
```bash
ssh -T -i ~/.ssh/homelab-deploy-key git@github.com

# Expected output:
# Hi ariel99gf/homelab! You've successfully authenticated...
```

### 5. ✅ k3s Cluster Running

```bash
# Test from your laptop
ansible raspberry_pi -i ansible/inventory/production.yml -m ping

# Verify k3s on control plane
ansible k3s_server -i ansible/inventory/production.yml -a "kubectl get nodes"
```

---

## 🚀 Running Phase 2

### Option 1: Complete Deployment (Recommended for first time)

```bash
cd ansible

# Deploy everything: k3s + ArgoCD + Apps
ansible-playbook -i inventory/production.yml playbooks/site.yml

# Estimated time: 15-25 minutes
```

**What happens:**
1. Phase 1: Optimize RPi nodes, deploy k3s
2. Phase 2: Install ArgoCD with SOPS
3. Phase 3: Bootstrap all applications
4. Phase 4: Verification and summary

### Option 2: Phase 2 Only (If k3s already running)

```bash
cd ansible

# Install ArgoCD only
ansible-playbook -i inventory/production.yml playbooks/gitops/deploy_argocd.yml

# Then bootstrap apps
ansible-playbook -i inventory/production.yml playbooks/gitops/bootstrap_apps.yml
```

### Option 3: Step-by-Step (For troubleshooting)

```bash
# Step 1: Deploy ArgoCD
ansible-playbook -i inventory/production.yml \
  playbooks/gitops/deploy_argocd.yml

# Step 2: Verify ArgoCD is ready
kubectl get pods -n argocd

# Step 3: Bootstrap applications
ansible-playbook -i inventory/production.yml \
  playbooks/gitops/bootstrap_apps.yml

# Step 4: Monitor sync
kubectl get applications -n argocd -w
```

---

## 🔍 Verification

### 1. Check ArgoCD Pods

```bash
kubectl get pods -n argocd

# Expected output (all Running):
# NAME                                  READY   STATUS
# argocd-application-controller-0       1/1     Running
# argocd-repo-server-xxx                2/2     Running  # ← 2/2 (SOPS sidecar)
# argocd-server-xxx                     1/1     Running
# ...
```

**⚠️ Important:** `argocd-repo-server` should show `2/2` (main + SOPS sidecar).

### 2. Check SOPS Plugin

```bash
kubectl logs -n argocd deployment/argocd-repo-server -c sops-plugin --tail=20

# Should see: Plugin initialization logs, no errors
```

### 3. Get ArgoCD Admin Password

```bash
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d && echo
```

### 4. Access ArgoCD UI

```bash
# Port forward
kubectl port-forward svc/argocd-server -n argocd 8080:443

# Open browser: https://localhost:8080
# Username: admin
# Password: <from step 3>
```

### 5. Check Applications

```bash
# List all applications
kubectl get applications -n argocd

# Check specific app status
kubectl describe application *** -n argocd

# Expected: Sync Status: Synced, Health Status: Healthy
```

### 6. Check Media Pods

```bash
kubectl get pods -n media -o wide

# Expected (on rasp-pi-04):
# ***-xxx      1/1  Running  rasp-pi-04
# ***-xxx      1/1  Running  rasp-pi-04
# ***-xxx    1/1  Running  rasp-pi-04
# ...
```

---

## ⚠️ Troubleshooting

### Issue 1: "Module 'kubernetes' not found"

```bash
# Install Python kubernetes library
pip3 install kubernetes

# Verify
python3 -c "import kubernetes; print('OK')"
```

### Issue 2: "Collection kubernetes.core not found"

```bash
# Install collection
ansible-galaxy collection install kubernetes.core

# Verify
ansible-galaxy collection list | grep kubernetes.core
```

### Issue 3: "SOPS age key not found"

```bash
# Check if key exists
ls -la ~/.config/sops/age/keys.txt

# If missing, check the setup section above
```

### Issue 4: "Repository authentication failed"

```bash
# Test SSH key manually
ssh -T -i ~/.ssh/homelab-deploy-key git@github.com

# If fails, regenerate and re-add to GitHub
```

### Issue 5: "argocd-repo-server shows 1/2 Ready"

```bash
# Check SOPS sidecar logs
kubectl logs -n argocd deployment/argocd-repo-server -c sops-plugin

# Common issue: SOPS age key not mounted
kubectl describe deployment argocd-repo-server -n argocd | grep -A5 sops-age
```

### Issue 6: "Applications stuck in Progressing"

```bash
# Check ArgoCD application controller logs
kubectl logs -n argocd statefulset/argocd-application-controller --tail=50

# Check specific application
kubectl describe application <app-name> -n argocd

# Force sync
kubectl patch application <app-name> -n argocd \
  --type merge -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### Issue 7: "SOPS decryption failed"

```bash
# Verify age key matches public key in .sops.yaml
grep 'public key:' ~/.config/sops/age/keys.txt
# Should output: age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja

# Check SOPS secret in cluster
kubectl get secret sops-age -n argocd -o yaml

# Verify repo-server can decrypt
kubectl exec -n argocd deployment/argocd-repo-server -c sops-plugin -- \
  sh -c 'echo "test" | sops --decrypt /dev/stdin 2>&1'
```

---

## 📊 Expected Timeline

| Phase | Duration | Notes |
|-------|----------|-------|
| Pre-flight checks | 2-3 min | Kubernetes API, SOPS keys |
| ArgoCD installation | 3-5 min | Download manifest, apply, wait for ready |
| SOPS configuration | 1-2 min | Create secret, patch repo-server |
| Repository setup | 1 min | Create SSH secret |
| Apps-root bootstrap | 1-2 min | Apply application |
| Application sync | 5-15 min | Depends on number of apps |
| **Total** | **13-28 min** | First-time deployment |

**Subsequent runs:** ~5-10 minutes (idempotent, skips existing resources)

---

## ✅ Success Criteria

Phase 2 is successful when:

- [ ] All ArgoCD pods are Running (5-6 pods)
- [ ] argocd-repo-server shows 2/2 Ready (main + SOPS sidecar)
- [ ] apps-root application is Synced
- [ ] All critical apps (***, ***, ***) are Healthy
- [ ] Media pods are running on rasp-pi-04
- [ ] Tailscale ingresses are accessible

---

## 🎯 Next Steps After Phase 2

1. **Access applications via Tailscale:**
   ```bash
   # Check ingresses
   kubectl get ingress -A

   # Test access
   curl -I https://***.tail57bf10.ts.net
   ```

2. **Configure SOPS-encrypted secrets** (if needed):
   ```bash
   # Edit encrypted secret
   cd k8s/apps/***
   sops ***-secret.sops.yaml

   # Commit and push
   git add ***-secret.sops.yaml
   git commit -m "Update *** VPN credentials"
   git push

   # ArgoCD will auto-sync (or force sync)
   kubectl patch application *** -n argocd \
     --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'
   ```

3. **Monitor resource usage:**
   ```bash
   kubectl top nodes
   kubectl top pods -A --sort-by=memory
   ```

4. **Set up Grafana dashboards** (if monitoring stack deployed)

5. **Run health checks periodically:**
   ```bash
   ansible-playbook -i inventory/production.yml \
     playbooks/maintenance/health_check.yml
   ```

---

## 📚 Additional Resources

- **ArgoCD Docs:** https://argo-cd.readthedocs.io/
- **SOPS Docs:** https://github.com/getsops/sops
- **Age Encryption:** https://github.com/FiloSottile/age
- **Kubernetes Python Client:** https://github.com/kubernetes-client/python

---

**Ready to deploy?** Follow the setup checklist, then run `site.yml`! 🚀
