# OCI ARM Always Free Migration Guide

**Date:** 2026-02-03
**Target:** Migrate from x86 (VM.Standard3.Flex) to ARM (VM.Standard.A1.Flex)
**Cost Impact:** Paid instances → Always Free (100% cost elimination)

---

## Pre-Migration Checklist

### ✅ Configuration Updates (COMPLETED)

- [x] Updated `variables.tf` with ARM image OCID
- [x] Updated `instance_shape` default to `VM.Standard.A1.Flex`
- [x] Updated `modules/compute/main.tf` with 2-digit naming (01, 02)
- [x] Added `lifecycle` block to force replacement
- [x] Created GitHub Actions capacity hunter workflow

### 📋 Before Execution

- [ ] Verify you have backups of any critical data
- [ ] Confirm GitHub Secrets are configured
- [ ] Test that SOPS decryption works locally
- [ ] Verify you can SSH into current instances (for final backup if needed)

---

## Configuration Summary

### Current State (x86)
| Instance | Shape | OCPUs | RAM | Cost |
|----------|-------|-------|-----|------|
| hl-k3s-node-0 | VM.Standard3.Flex | 1-2 | 8GB | Paid |
| hl-k3s-node-1 | VM.Standard3.Flex | 1-2 | 8GB | Paid |

### Target State (ARM)
| Instance | Shape | OCPUs | RAM | Cost |
|----------|-------|-------|-----|------|
| hl-k3s-node-01 | VM.Standard.A1.Flex | 2 | 12GB | **Always Free** |
| hl-k3s-node-02 | VM.Standard.A1.Flex | 2 | 12GB | **Always Free** |

**Total Always Free Allocation:** 4 OCPUs, 24 GB RAM

### ARM Ubuntu Image
- **Name:** Canonical-Ubuntu-24.04-aarch64-2025.01.31-1
- **OCID:** `ocid1.image.oc1.sa-saopaulo-1.aaaaaaaaaidkaxag5ju3kvdosvmi4dqxux6yhee7pjxkm4oqbbhmbb55an7a`
- **Architecture:** ARM64 (aarch64)
- **Release Date:** March 22, 2025

---

## Migration Execution

### Option 1: Terraform Taint (Recommended)

Forces Terraform to mark resources for recreation:

```bash
# Navigate to Terraform directory
cd infra/oci

# Taint both instances to force replacement
terraform taint 'module.k3s_nodes.oci_core_instance.k3s_node[0]'
terraform taint 'module.k3s_nodes.oci_core_instance.k3s_node[1]'

# Verify the plan shows replacement
terraform plan

# Expected output:
# Plan: 2 to add, 0 to change, 2 to destroy.

# Execute the migration
terraform apply
```

### Option 2: Targeted Destroy & Recreate

More explicit approach:

```bash
cd infra/oci

# Destroy only the compute module (keeps network intact)
terraform destroy -target='module.k3s_nodes.oci_core_instance.k3s_node[0]'
terraform destroy -target='module.k3s_nodes.oci_core_instance.k3s_node[1]'

# Recreate with ARM configuration
terraform apply
```

### Option 3: Complete Module Destroy

If you want to be extra sure:

```bash
cd infra/oci

# Destroy entire compute module
terraform destroy -target='module.k3s_nodes'

# Recreate everything
terraform apply
```

---

## Handling "Out of Capacity" Errors

ARM Always Free instances in sa-saopaulo-1 may have limited capacity.

### If `terraform apply` fails with capacity error:

**Manual Approach:**
```bash
# Try applying multiple times (capacity is released frequently)
for i in {1..5}; do
  echo "Attempt $i..."
  terraform apply -auto-approve && break
  sleep 300  # Wait 5 minutes between attempts
done
```

**Automated Approach (Recommended):**
Enable the GitHub Actions workflow:

```bash
# Push changes to GitHub
git add .
git commit -m "feat: migrate to ARM Always Free instances"
git push origin main

# The workflow will automatically hunt for capacity every 15 minutes
```

---

## Post-Migration Verification

### 1. Verify Instance Details

```bash
# Check instance shape and configuration
oci compute instance list \
  --compartment-id $OCI_COMPARTMENT_ID \
  --query "data[?contains(\"display-name\", 'k3s-node')].{name:\"display-name\", shape:shape, ocpus:\"shape-config\".ocpus, memory:\"shape-config\".\"memory-in-gbs\", state:\"lifecycle-state\"}" \
  --output table
```

**Expected Output:**
```
+------------------+----------------------+-------+---------+----------+
| name             | shape                | ocpus | memory  | state    |
+------------------+----------------------+-------+---------+----------+
| hl-k3s-node-01   | VM.Standard.A1.Flex  | 2     | 12      | RUNNING  |
| hl-k3s-node-02   | VM.Standard.A1.Flex  | 2     | 12      | RUNNING  |
+------------------+----------------------+-------+---------+----------+
```

### 2. Verify Always Free Status

In the OCI Console:
1. Navigate to **Compute → Instances**
2. Check that each instance has the **"Always Free"** badge
3. Verify total allocation: **4 OCPUs, 24 GB RAM**

### 3. Test SSH Connectivity

```bash
# Get instance IPs from Terraform
terraform output -json | jq -r '.k3s_node_public_ips.value[]'

# Test SSH (replace with actual IP)
ssh ubuntu@<instance-ip>

# Verify architecture
uname -m
# Expected: aarch64
```

### 4. Verify Tailscale Connectivity

```bash
# Check Tailscale status on each node
ssh ubuntu@<instance-ip> "sudo tailscale status"

# Verify nodes appear in Tailscale admin console
```

---

## Rollback Plan (If Needed)

If migration fails and you need to revert to x86:

```bash
# 1. Update variables.tf back to x86 image
# Change image OCID back to original x86 Ubuntu image

# 2. Update instance_shape
# Change back to VM.Standard3.Flex

# 3. Apply changes
terraform apply
```

---

## Redeploy K3s Cluster

After migration is complete, redeploy your K3s cluster:

```bash
# Generate Ansible inventory
cd infra/oci
terraform output -json > outputs.json

# Run Ansible playbook (assuming you have one)
ansible-playbook -i hosts.ini playbooks/k3s-install.yaml

# Verify K3s cluster
kubectl get nodes -o wide
```

**Expected Output:**
```
NAME          STATUS   ROLES           AGE   VERSION   INTERNAL-IP   EXTERNAL-IP     OS-IMAGE             KERNEL-VERSION     CONTAINER-RUNTIME
k3s-node-01   Ready    control-plane   5m    v1.28.x   10.0.1.x      x.x.x.x         Ubuntu 24.04 LTS     6.x.x-arm64        containerd://1.7.x
k3s-node-02   Ready    worker          5m    v1.28.x   10.0.1.x      x.x.x.x         Ubuntu 24.04 LTS     6.x.x-arm64        containerd://1.7.x
```

---

## GitHub Actions Capacity Hunter

The workflow at `.github/workflows/oci-provisioner.yml` provides automated capacity hunting.

### Features:
- **Schedule:** Runs every 15 minutes
- **Smart Detection:** Only provisions if < 2 instances exist
- **Graceful Errors:** Continues on "Out of Capacity" errors
- **Partial Success:** Allows 1 of 2 instances, retries for 2nd
- **Notifications:** Optional Slack alerts when complete

### To Enable:

1. **Configure GitHub Secrets:**
   ```
   AGE_KEY
   OCI_USER_OCID
   OCI_TENANCY_OCID
   OCI_FINGERPRINT
   OCI_PRIVATE_KEY
   OCI_COMPARTMENT_ID
   TF_BACKEND_ADDRESS
   TF_BACKEND_LOCK_ADDRESS
   TF_BACKEND_UNLOCK_ADDRESS
   ```

2. **Push to GitHub:**
   ```bash
   git push origin main
   ```

3. **Monitor Actions Tab:**
   - Workflow runs every 15 minutes
   - Check logs for capacity hunting progress
   - Workflow stops automatically when 2 instances are running

### Manual Trigger:

```bash
# Via GitHub CLI
gh workflow run oci-provisioner.yml -f reason="Manual capacity check"
```

---

## Cost Savings Calculation

### Monthly Cost Comparison

**Before (x86 - Paid):**
- 2x VM.Standard3.Flex instances
- Variable cost depending on OCPU/RAM allocation
- Estimated: $20-50/month (region dependent)

**After (ARM - Always Free):**
- 2x VM.Standard.A1.Flex instances
- 4 OCPUs, 24 GB RAM
- Cost: **$0/month** ✅

**Annual Savings:** $240-600/year

---

## Troubleshooting

### Problem: "Out of capacity" error persists

**Solution 1:** Use GitHub Actions automated retry
```bash
# Workflow retries every 15 minutes automatically
# Capacity is typically available within 24-48 hours
```

**Solution 2:** Try different availability domain
```hcl
# In modules/compute/main.tf, change:
availability_domain = data.oci_identity_availability_domains.ads.availability_domains[1].name
```

**Solution 3:** Create instances one at a time
```bash
# Temporarily set instance_count to 1
terraform apply -var="instance_count=1"

# After first instance is created, increase to 2
terraform apply -var="instance_count=2"
```

### Problem: Instance won't boot / hangs

**Cause:** Wrong architecture image (x86 image on ARM instance)

**Solution:**
```bash
# Verify image OCID is for ARM64
oci compute image get --image-id <your-image-ocid> \
  --query 'data."operating-system"'

# Should show: "Canonical Ubuntu" with "aarch64" architecture
```

### Problem: Tailscale not connecting

**Solution:**
```bash
# Check cloud-init logs
ssh ubuntu@<instance-ip> "sudo cat /var/log/cloud-init-output.log | grep tailscale"

# Manually install Tailscale if needed
ssh ubuntu@<instance-ip> "curl -fsSL https://tailscale.com/install.sh | sh"
```

---

## Success Criteria

- [ ] 2 instances running with ARM shape (VM.Standard.A1.Flex)
- [ ] Total resources: 4 OCPUs, 24 GB RAM
- [ ] "Always Free" badge visible in OCI Console
- [ ] Both instances show `aarch64` architecture
- [ ] Tailscale connectivity working
- [ ] K3s cluster deployed and nodes ready
- [ ] Monthly cost: $0

---

## Next Steps After Migration

1. **Redeploy Services:** Use your existing IaC (Kubernetes manifests, Helm charts)
2. **Restore Data:** Apply backups for persistent data (if needed)
3. **Update DNS:** If using custom DNS, update A records
4. **Monitor Performance:** ARM performance may differ slightly from x86
5. **Document:** Update your homelab documentation with ARM-specific notes

---

## Important Notes

⚠️ **Data Loss Warning:** This migration DESTROYS and RECREATES instances. All local disk data will be lost. Ensure you have backups!

✅ **Always Free Guarantee:** ARM instances meeting the Always Free criteria (4 OCPUs, 24 GB RAM total) will never incur charges, even if you exceed other free tier limits.

🔄 **Capacity Availability:** ARM Always Free capacity is limited. The GitHub Actions workflow provides automated capacity hunting if initial terraform apply fails.

📊 **Performance:** ARM performance is excellent for homelab workloads. Most workloads run at similar or better performance compared to equivalent x86 instances.

---

**Questions or issues?** Check the troubleshooting section or review Terraform logs for specific error messages.
