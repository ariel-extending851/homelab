# Production Readiness Review - 2026-02-05

**Reviewer:** Tech Lead (Senior DevOps Engineer)
**Review Date:** February 5, 2026
**Scope:** 14 files, 890+ lines changed
**Context:** AWS infrastructure expansion, Ansible automation, and documentation updates

---

## Executive Summary

**FINAL VERDICT:** 🟡 **APPROVE WITH CHANGES**

**Critical Issues:** 1
**Medium Issues:** 3
**Low Issues:** 2

**Summary:** The changes introduce AWS infrastructure automation and Ansible deployment capabilities. While the Terraform code follows good security practices (IMDSv2, EBS encryption, SOPS), there are **critical issues with the Ansible playbook security** and **binary tfplan files committed to git** that must be addressed before production deployment.

---

## 🔴 CRITICAL ISSUES (BLOCKING)

### 1. 🔴 Insecure SSH Configuration in Ansible Playbook

**File:** `ansible/playbooks/deploy_k3s.yml`
**Line:** 23
**Severity:** CRITICAL (Security Vulnerability)

**Issue:**
```yaml
ssh -o StrictHostKeyChecking=no -i {{ ansible_ssh_private_key_file | default('~/.ssh/homelab-aws') }}
```

**Problem:** The playbook uses `StrictHostKeyChecking=no`, which **disables host key verification**. This makes the deployment vulnerable to **Man-in-the-Middle (MITM) attacks** where an attacker could intercept the SSH connection and capture the k3s node token (a sensitive credential).

**AWS DOP-C02 Principle Violated:** Security best practices mandate strict SSH host key verification in production environments.

**Fix Required:**
```yaml
# OPTION 1: Pre-populate known_hosts (RECOMMENDED)
- name: Add k3s server to known_hosts
  ansible.builtin.known_hosts:
    name: "{{ hostvars[groups['k3s_server'][0]]['public_ip'] }}"
    key: "{{ lookup('pipe', 'ssh-keyscan -H ' + hostvars[groups['k3s_server'][0]]['public_ip']) }}"
    state: present
  delegate_to: localhost

- name: Retrieve k3s token from server
  ansible.builtin.command: >
    ssh -i {{ ansible_ssh_private_key_file | default('~/.ssh/homelab-aws') }}
    ec2-user@{{ hostvars[groups['k3s_server'][0]]['public_ip'] }}
    'sudo cat /var/lib/rancher/k3s/server/node-token'
  register: k3s_token_result
  delegate_to: localhost
  changed_when: false
  no_log: true

# OPTION 2: Use Ansible's built-in SSH (BETTER)
- name: Retrieve k3s token from server
  ansible.builtin.slurp:
    src: /var/lib/rancher/k3s/server/node-token
  register: k3s_token_result
  delegate_to: "{{ groups['k3s_server'][0] }}"
  no_log: true

- name: Set k3s token fact
  ansible.builtin.set_fact:
    k3s_node_token: "{{ k3s_token_result['content'] | b64decode | trim }}"
  no_log: true
```

**Recommendation:** Use **OPTION 2** (Ansible's `slurp` module) to eliminate nested SSH entirely and leverage Ansible's native connection handling.

---

### 2. 🔴 Binary Terraform Plan Files Committed to Git

**Files:**
- `infra/aws/tfplan.localstack` (20 KB)
- `infra/oci/arm-migration.tfplan` (33 KB)
- `infra/oci/arm-migration-v2.tfplan` (27 KB)
- `infra/oci/single-arm.tfplan` (27 KB)

**Severity:** CRITICAL (Secret Exposure Risk)

**Problem:** Terraform plan files are **binary archives** that may contain:
- Sensitive variable values (even if marked `sensitive = true`)
- Resource IDs and internal state
- Cloud provider credentials (in rare cases)

**Evidence:**
```bash
$ file infra/aws/tfplan.localstack
Zip archive data, made by v2.0, extract using at least v2.0
```

**AWS DOP-C02 Principle Violated:** "Never commit secrets or sensitive operational data to version control."

**Fix Required:**
```bash
# Remove binary files from commit
git reset HEAD infra/aws/tfplan.localstack
git reset HEAD infra/oci/*.tfplan

# Add to .gitignore
echo "*.tfplan" >> .gitignore
echo "tfplan.*" >> .gitignore

# Purge from history (if already committed)
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch infra/aws/tfplan.localstack infra/oci/*.tfplan' \
  --prune-empty --tag-name-filter cat -- --all
```

**Rationale:** Terraform plan files are **development artifacts** that should only exist locally or in CI/CD pipelines with proper secret management (e.g., encrypted artifacts in GitHub Actions).

---

## 🟡 MEDIUM ISSUES (Should Fix Before Production)

### 3. 🟡 Missing Resource Limits in k3s Deployment

**File:** `infra/aws/modules/compute/templates/user_data.tftpl`
**Lines:** 56-77 (k3s server install)
**Severity:** MEDIUM (Raspberry Pi Constraint Violation)

**Issue:** The k3s installation does not configure **memory limits or reservations** for system components. While this affects AWS nodes (t3.small = 2 GB RAM), it's **critical** for future Raspberry Pi integration:

- **Pi3:** 1 GB RAM (requires aggressive resource limits)
- **Pi4:** 4 GB RAM (requires careful planning)

**Current Installation:**
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${k3s_version}" \
  K3S_TOKEN="${k3s_token}" \
  INSTALL_K3S_EXEC="server" \
  sh -s - \
    --disable traefik \
    --disable servicelb \
    --write-kubeconfig-mode 644
```

**Fix Required:**
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="${k3s_version}" \
  K3S_TOKEN="${k3s_token}" \
  INSTALL_K3S_EXEC="server" \
  sh -s - \
    --disable traefik \
    --disable servicelb \
    --write-kubeconfig-mode 644 \
    --kube-apiserver-arg="--max-requests-inflight=200" \
    --kube-apiserver-arg="--max-mutating-requests-inflight=100" \
    --kubelet-arg="--kube-reserved=cpu=100m,memory=512Mi" \
    --kubelet-arg="--system-reserved=cpu=100m,memory=512Mi" \
    --kubelet-arg="--eviction-hard=memory.available<5%"
```

**Impact:** Without these limits, k3s could consume all available memory on constrained hardware, causing node instability.

---

### 4. 🟡 SOPS Encrypted Files Updated Without Documentation

**Files:**
- `infra/aws/terraform.tfvars.sops.yaml` (ssh_public_key changed)
- `infra/oci/terraform.tfvars.sops.yaml` (multiple paths changed)

**Severity:** MEDIUM (Operational Risk)

**Issue:** The encrypted values changed (different ciphertext), but there's **no commit message explanation** for:
- Why the SSH public key changed
- Whether private keys were rotated
- Whether the old keys should be revoked

**AWS DOP-C02 Principle:** "Document all credential rotations with justification and rollback plan."

**Fix Required:**
Add a section to the commit message:
```
SOPS Changes:
- AWS: Rotated SSH keypair for homelab-aws (old key: ssh-rsa AAAA...4kKA, new key: ssh-rsa AAAA...lIko)
- OCI: Updated file paths to use absolute paths (~/.../.ssh/oci_homelab_rsa)
- Reason: Preparing for multi-user access with individual keys
- Rollback: Restore previous terraform.tfvars.sops.yaml from commit abc123
```

---

### 5. 🟡 Naming Convention Violation in Terraform Resources

**File:** `infra/aws/modules/compute/main.tf`
**Lines:** 88, 138, 212
**Severity:** MEDIUM (Convention Violation)

**Issue:** The new launch templates use `name_prefix` but don't follow the `hl-` prefix convention consistently:

```hcl
# Line 88 - CORRECT
resource "aws_launch_template" "k3s_server" {
  name_prefix = "hl-k3s-server-"  # ✅ GOOD
}

# Line 138 - CORRECT
resource "aws_launch_template" "k3s_agent" {
  name_prefix = "hl-k3s-agent-"  # ✅ GOOD
}

# Line 212 - CORRECT
resource "aws_launch_template" "k3s_agent_final" {
  name_prefix = "hl-k3s-agent-final-"  # ✅ GOOD
}
```

**Upon Re-Review:** All launch templates correctly use the `hl-` prefix. **Issue RESOLVED** ✅

---

## 🟢 LOW ISSUES (Non-Blocking Observations)

### 6. 🟢 Hardcoded kubeconfig Permission (644)

**File:** `infra/aws/modules/compute/templates/user_data.tftpl`
**Line:** 63
**Severity:** LOW (Security Best Practice)

**Issue:**
```bash
--write-kubeconfig-mode 644
```

**Problem:** Mode `644` makes the kubeconfig **world-readable**, allowing any user on the system to access cluster credentials.

**Production Best Practice:**
```bash
--write-kubeconfig-mode 600  # Owner read/write only
```

**Exception:** In a homelab environment with single-user EC2 instances, this is **acceptable** for convenience. However, document this decision.

---

### 7. 🟢 Missing Executable Bit on Python Inventory Script

**File:** `ansible/terraform_inventory_aws.py`
**Severity:** LOW (Usability)

**Issue:** The file has a shebang (`#!/usr/bin/env python3`) but may not have the executable bit set in git.

**Fix:**
```bash
chmod +x ansible/terraform_inventory_aws.py
git update-index --chmod=+x ansible/terraform_inventory_aws.py
```

**Verify:**
```bash
git ls-files -s ansible/terraform_inventory_aws.py
# Should show: 100755 (not 100644)
```

---

## ✅ SECURITY VALIDATIONS PASSED

### Terraform AWS Infrastructure

| Check | Status | Evidence |
|-------|--------|----------|
| **No hardcoded secrets** | ✅ PASS | All secrets via SOPS encryption |
| **IMDSv2 enforced** | ✅ PASS | `http_tokens = "required"` (lines 105, 157) |
| **EBS encryption enabled** | ✅ PASS | `encrypted = true` (lines 99, 145) |
| **No privileged containers** | ✅ PASS | EC2 instances, not containers |
| **No dangerous capabilities** | ✅ PASS | Standard IAM role (SSM only) |
| **Proper `hl-` prefix** | ✅ PASS | All resources use `hl-k3s-*` naming |
| **No `chmod 777`** | ✅ PASS | No dangerous permissions |
| **Spot instance limits** | ✅ PASS | `price-capacity-optimized` strategy |

### Ansible Automation

| Check | Status | Evidence |
|-------|--------|----------|
| **No plaintext secrets** | ✅ PASS | k3s token retrieved dynamically, marked `no_log: true` |
| **Proper SSH key handling** | 🔴 FAIL | Uses `StrictHostKeyChecking=no` (CRITICAL ISSUE #1) |
| **Idempotent playbooks** | ✅ PASS | Uses `changed_when: false` where appropriate |

---

## 📊 RASPBERRY PI CONSTRAINT ANALYSIS

**Context:** These changes prepare for future Raspberry Pi integration (per `docs/architecture.md`).

| Constraint | Current AWS Setup | Pi3 Requirements | Pi4 Requirements | Compliance |
|------------|-------------------|------------------|------------------|------------|
| **Memory Limits** | None (2 GB t3.small) | MUST be <512 Mi per pod | MUST be <1 Gi per pod | 🟡 Missing |
| **Storage I/O** | gp3 EBS (AWS SSD) | SD card (slow writes) | SD card (slow writes) | ✅ N/A (cloud) |
| **ARM64 Images** | Amazon Linux 2023 (x86) | ARM64v8 required | ARM64v8 required | 🟢 AWS uses amd64 (OK for now) |
| **Node Selectors** | None | MUST have `arch=arm64` | MUST have `arch=arm64` | 🟡 Missing in k8s manifests (future) |

**Recommendation:** Add resource limits now (Issue #3) to establish the pattern before Pi nodes join.

---

## 🚨 BLOCKING ISSUES SUMMARY

Before this commit can be approved for production:

1. **MUST FIX:** Remove `StrictHostKeyChecking=no` from Ansible playbook (CRITICAL SECURITY)
2. **MUST REMOVE:** All `*.tfplan` binary files from commit (SECRET EXPOSURE RISK)
3. **SHOULD FIX:** Add k3s resource limits for future Pi compatibility (MEDIUM PRIORITY)
4. **SHOULD DOCUMENT:** Explain SOPS credential rotation in commit message (MEDIUM PRIORITY)

---

## 📋 FINAL RECOMMENDATION

### **🟡 APPROVE WITH CHANGES**

**Required Actions Before Commit:**

```bash
# 1. Remove binary tfplan files
git reset HEAD infra/aws/tfplan.localstack infra/oci/*.tfplan
echo "*.tfplan" >> infra/aws/.gitignore
echo "*.tfplan" >> infra/oci/.gitignore

# 2. Fix Ansible SSH security
# Edit ansible/playbooks/deploy_k3s.yml - replace nested SSH with slurp module
# (See detailed fix in CRITICAL ISSUE #1)

# 3. Add resource limits to k3s installation
# Edit infra/aws/modules/compute/templates/user_data.tftpl
# (See detailed fix in MEDIUM ISSUE #3)

# 4. Set executable bit on Python script
chmod +x ansible/terraform_inventory_aws.py
git add ansible/terraform_inventory_aws.py

# 5. Update commit message to document SOPS changes
git commit --amend  # Add credential rotation details
```

**Estimated Time to Fix:** 30-45 minutes

---

## 📝 POSITIVE OBSERVATIONS

The following aspects demonstrate **production-grade engineering**:

1. ✅ **Comprehensive Documentation:** The `ansible/README.md` expansion is excellent (225 lines, clear examples)
2. ✅ **Security by Default:** IMDSv2, EBS encryption, SOPS integration
3. ✅ **Infrastructure as Code:** Proper Terraform module structure
4. ✅ **Cost Optimization:** Spot instances with `price-capacity-optimized` strategy
5. ✅ **Dynamic Inventory:** Proper implementation of Terraform → Ansible integration
6. ✅ **No `latest` Tags:** All k3s versions pinned (e.g., `v1.28.5+k3s1`)

---

## 🎓 AWS DOP-C02 EXAM ALIGNMENT

This implementation demonstrates the following DOP-C02 competencies:

- **Domain 1 (SDLC Automation):** Ansible for configuration management, dynamic inventory
- **Domain 2 (Configuration Management):** Terraform modules, SOPS for secrets
- **Domain 3 (Resilient Cloud Solutions):** Spot instances, multi-AZ potential
- **Domain 4 (Monitoring & Logging):** CloudWatch integration (implicit via EC2)
- **Domain 5 (Incident Response):** IAM least privilege, IMDSv2 for SSRF protection

**Exam Tip:** The dynamic inventory pattern (Terraform → Ansible) is a common question topic for hybrid/multi-cloud scenarios.

---

## 📚 REFERENCES

- [Ansible Security Best Practices](https://docs.ansible.com/ansible/latest/tips_tricks/ansible_tips_tricks.html#security)
- [Terraform Sensitive Data in State](https://developer.hashicorp.com/terraform/language/state/sensitive-data)
- [AWS IMDSv2 Security](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-service.html)
- [k3s Resource Management](https://docs.k3s.io/installation/requirements#resource-profiling)

---

**Review Completed:** 2026-02-05 @ 14:23 UTC
**Reviewer Signature:** Tech Lead (Claude Code Assistant)
**Next Review Required:** After implementing fixes (estimated 1 hour)
