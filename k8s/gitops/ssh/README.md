# ArgoCD SSH Authentication

This directory contains the SSH keypair used by ArgoCD to authenticate with the GitHub repository.

## 🔑 Key Files

- `argocd` - ED25519 private key (excluded from VCS via `.gitignore`)
- `argocd.pub` - ED25519 public key (also excluded, but safe to share)

## 🚀 Setup Instructions

### 1. Add Deploy Key to GitHub Repository

1. Copy the public key to clipboard:
   ```bash
   cat k8s/gitops/ssh/argocd.pub
   ```

2. Navigate to: https://github.com/ariel-extending851/homelab/settings/keys/new

3. Configure Deploy Key:
   - **Title:** `ArgoCD Deploy Key (Read-Only)`
   - **Key:** Paste the public key content
   - **Allow write access:** ❌ **UNCHECKED** (Read-only access only)

4. Click **"Add key"**

### 2. Create Kubernetes Secret

Apply the repository secret manifest:
```bash
kubectl apply -f k8s/gitops/argocd-repo-ssh-secret.yaml
```

### 3. Verify ArgoCD Connection

Check if ArgoCD can authenticate with the repository:
```bash
# Via ArgoCD CLI (if installed)
argocd repo list

# Via kubectl (check secret exists)
kubectl get secret -n argocd argocd-repo-homelab -o yaml

# Force ArgoCD to refresh the App-of-Apps
kubectl patch application homelab-apps-root -n argocd \
  --type merge \
  -p '{"metadata":{"annotations":{"argocd.argoproj.io/refresh":"normal"}}}'
```

### 4. Monitor Application Sync

```bash
# Watch ArgoCD application status
kubectl get application -n argocd -w

# Check ArgoCD server logs for authentication issues
kubectl logs -n argocd deployment/argocd-server --tail=50
```

## 🔐 Security Guardrails

- ✅ **ED25519 Algorithm:** Modern, secure, and shorter key length (256-bit)
- ✅ **Read-Only Deploy Key:** GitHub Deploy Keys enforce least privilege
- ✅ **Private Key Excluded:** `.gitignore` prevents accidental commits
- ✅ **No Passphrases:** ArgoCD requires non-interactive authentication
- ✅ **Key Rotation:** Regenerate keys annually or after security incidents

## 🔄 Key Rotation (Annual Maintenance)

1. Generate new keypair:
   ```bash
   ssh-keygen -t ed25519 -C "argocd@homelab-cluster-$(date +%Y)" \
     -f k8s/gitops/ssh/argocd -N ""
   ```

2. Update GitHub Deploy Key (replace old key)

3. Re-apply Kubernetes secret:
   ```bash
   kubectl delete secret -n argocd argocd-repo-homelab
   kubectl apply -f k8s/gitops/argocd-repo-ssh-secret.yaml
   ```

4. Force ArgoCD refresh (see step 3 above)

## 📚 References

- [ArgoCD Private Repositories](https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/)
- [GitHub Deploy Keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)
- [SSH Key Types](https://goteleport.com/blog/comparing-ssh-keys/)
