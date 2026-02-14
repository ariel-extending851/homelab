# Code Review: Zero Trust Tailscale + k3s v1.34.3 Migration

**Reviewer:** Tech Lead (claude-opus-4-6)
**Date:** 2026-02-14
**Files:** 10 files, +139/-155 lines
**Recommendation:** **APPROVE WITH CHANGES** (2 medium, 3 low -- no blockers)

---

## Executive Summary

This is a well-architected migration to Zero Trust networking. The removal of all public ingress (SSH port 22, k3s API port 6443) in favor of Tailscale WireGuard mesh is the correct production-grade approach per AWS DOP-C02 defense-in-depth principles. The k3s version bump to v1.34.3+k3s1 aligns with existing Pi agents. SOPS encryption is properly configured. No secrets are exposed in plaintext.

**What's excellent:**
- Zero Trust SG: only self-referencing ingress + egress. No `0.0.0.0/0` ingress anywhere.
- `tailscale_auth_key` is `sensitive = true` at all module levels and SOPS-encrypted with AGE.
- IMDSv2 enforced (`http_tokens = "required"`) on all three launch templates.
- EBS encryption at rest enabled on all volumes (`encrypted = true`).
- `set -euo pipefail` in user_data -- script fails fast on errors.
- Removed premature CloudNativePG install from user_data (correct -- infra provisioning should not install application workloads).
- LocalStack mock secrets are obviously fake (`tskey-auth-mock-localstack-testing-only`).
- `encrypted_regex` updated to include `tailscale_auth_key` -- SOPS will encrypt all three secret fields.
- k3s `--flannel-iface=tailscale0` and `--node-ip=$TAILSCALE_IP` correctly routes inter-node traffic over WireGuard.
- Previous review's critical issues (tfplan files, Ansible SSH) are not present in this changeset.

---

## Issues

### M1. `--write-kubeconfig-mode 644` -- world-readable kubeconfig

| | |
|---|---|
| **Severity** | MEDIUM |
| **File** | `infra/aws/modules/compute/templates/user_data.tftpl:105` |

**Description:** The kubeconfig at `/etc/rancher/k3s/k3s.yaml` is set to mode `644`, making it readable by all users on the node. This file contains the cluster admin certificate and private key. While the node is behind Tailscale (so only authorized users can reach it), any process running as any user on the node can read the full cluster-admin kubeconfig.

**Why it matters:** Principle of least privilege. If a compromised container escapes to the host via a kernel exploit, it gets cluster-admin for free. This was flagged as Low (L6) in the previous review -- it should now be addressed as part of this security hardening PR.

**Fix:**
```diff
-    --write-kubeconfig-mode 644 \
+    --write-kubeconfig-mode 600 \
```

If non-root tools need kubeconfig access, use `K3S_KUBECONFIG_MODE=640` and add the `ec2-user` to the appropriate group.

---

### M2. EBS volume size validation mismatch between root and compute module

| | |
|---|---|
| **Severity** | MEDIUM |
| **File** | `infra/aws/modules/compute/variables.tf:20` vs `infra/aws/variables.tf:31` |

**Description:** Root module enforces `>= 30 && <= 100` but compute module still allows `>= 20 && <= 100`. This inconsistency means the compute module's validation is misleading -- it claims to accept 20GB but the root module will never pass a value below 30. Future module consumers will read the compute module validation and believe 20GB is valid.

**Fix:**
```diff
# infra/aws/modules/compute/variables.tf
  validation {
-    condition     = var.ebs_volume_size >= 20 && var.ebs_volume_size <= 100
-    error_message = "EBS volume size must be between 20GB and 100GB."
+    condition     = var.ebs_volume_size >= 30 && var.ebs_volume_size <= 100
+    error_message = "EBS volume size must be between 30GB and 100GB (practical minimum for k3s cluster)."
  }
```

---

### L1. Misleading comment about `--advertise-tags` in user_data

| | |
|---|---|
| **Severity** | LOW |
| **File** | `infra/aws/modules/compute/templates/user_data.tftpl:61` |

**Description:** Comment says `# --advertise-tags: tag nodes for ACL policies` but the actual `tailscale up` command (lines 64-67) does NOT include `--advertise-tags`. This is misleading documentation that will confuse future operators.

**Fix:** Either add the flag or remove the comment:
```diff
 # Join the tailnet with the auth key
-# --advertise-tags: tag nodes for ACL policies
 # --accept-routes: accept routes from other tailnet nodes
 # --hostname: set a recognizable hostname in the tailnet
```

---

### L2. Tailscale install via pipe-to-shell (`curl | sh`)

| | |
|---|---|
| **Severity** | LOW |
| **File** | `infra/aws/modules/compute/templates/user_data.tftpl:55` |

**Description:** `curl -fsSL https://tailscale.com/install.sh | sh` is a pipe-to-shell install with no integrity verification (no checksum, no GPG signature check). A supply-chain attack on `tailscale.com` would compromise all new nodes.

**Why it's Low not Medium:** This is Tailscale's official installation method, the `-f` flag ensures curl fails on HTTP errors, the node is an ephemeral spot instance, and the k3s install script uses the same pattern. This is an accepted industry practice for bootstrapping.

**Recommended future improvement:** Bake Tailscale into the AMI with Packer (aligns with `docs/architecture.md` mention of Packer for immutable infrastructure), or use the Tailscale RPM repo with `dnf install tailscale` and pin a specific version.

---

### L3. `ec2-metadata` command assumed available -- should use IMDSv2 token pattern

| | |
|---|---|
| **Severity** | LOW |
| **File** | `infra/aws/modules/compute/templates/user_data.tftpl:100,102,108,119,139` |

**Description:** The script uses `ec2-metadata --public-ipv4` and `ec2-metadata --availability-zone` to retrieve instance metadata. On Amazon Linux 2023, the `ec2-metadata` utility availability depends on the AMI variant. More importantly, since this infrastructure enforces IMDSv2 (`http_tokens = "required"`), the script should use the IMDSv2 token-based approach for consistency and resilience.

**Fix (recommended for follow-up):**
```bash
# IMDSv2-compliant metadata retrieval (consistent with launch template enforcement)
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
  -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
PUBLIC_IP=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/public-ipv4)
AZ=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
  http://169.254.169.254/latest/meta-data/placement/availability-zone)
```

---

## Security Checklist

| Check | Status | Notes |
|-------|--------|-------|
| No plaintext secrets in staged files | PASS | All values are `ENC[AES256_GCM,...]` or obviously mock |
| No `0.0.0.0/0` ingress | PASS | Only egress uses `0.0.0.0/0` (required for outbound) |
| No `chmod 777` or dangerous permissions | PASS | Only `chmod +x` and `chmod 600` in docs (appropriate) |
| SOPS `encrypted_regex` covers all secrets | PASS | `^(ssh_public_key\|k3s_token\|tailscale_auth_key)$` |
| SOPS AGE key matches `.sops.yaml` | PASS | `age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja` consistent across repo |
| `sensitive = true` on all secret variables | PASS | `tailscale_auth_key`, `k3s_token`, `ssh_public_key` -- all marked at both root and module level |
| IMDSv2 enforced | PASS | `http_tokens = "required"` on all 3 launch templates (lines 114, 175, 279) |
| EBS encryption enabled | PASS | `encrypted = true` on all block device mappings |
| IAM least privilege | PASS | Only `AmazonSSMManagedInstanceCore` managed policy attached |
| IAM policy ARN valid | PASS | `arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore` -- correct 6-part ARN |
| No `:latest` image tags | N/A | No container images in this changeset |
| k3s version pinned | PASS | `v1.34.3+k3s1` -- specific version, not `latest` |
| No binary/tfplan files staged | PASS | Previous review's critical issue resolved |

## Raspberry Pi Constraints Checklist

| Check | Status | Notes |
|-------|--------|-------|
| Container memory limits | N/A | No K8s manifests in this changeset (EC2 infra only) |
| Pi3 RAM budget (<=512Mi) | N/A | These are EC2 t3.small instances (2GB RAM) |
| SD card I/O avoidance | N/A | EBS gp3 volumes, not SD cards |

## Naming & Architecture Checklist (per `docs/conventions.md`)

| Check | Status | Notes |
|-------|--------|-------|
| `hl-` prefix on all resources | PASS | `hl-k3s-server`, `hl-k3s-agent`, `hl-k3s-cluster-`, `hl-k3s-node-`, `hl-homelab-key` |
| kebab-case naming | PASS | All resource names use kebab-case consistently |
| Consistent tag structure | PASS | `Name`, `Project`, `ManagedBy`, `Environment` tags via `default_tags` |
| No naming convention violations | PASS | All `name_prefix` values follow `hl-` pattern |

## Infrastructure Best Practices

| Check | Status | Notes |
|-------|--------|-------|
| Spot instance interruption handling | PASS | `instance_interruption_behavior = "terminate"` with `type = "maintain"` |
| `create_before_destroy` lifecycle | PASS | On security group resource |
| Validation blocks on all user-facing vars | PASS | `instance_type`, `ebs_volume_size`, `k3s_version`, `localstack_test` all validated |
| `set -euo pipefail` in user_data | PASS | Script fails fast on any error |
| Tailscale IP wait with timeout + hard exit | PASS | 30 iterations x 2s = 60s timeout, `exit 1` on failure |
| Egress-only `0.0.0.0/0` (no ingress) | PASS | Required for Tailscale DERP, container pulls, OS updates |
| SSM Session Manager for emergency access | PASS | IAM role attached, no SSH ingress needed |
| SOPS version pinned | PASS | `version: 3.11.0` in encrypted file metadata |

---

## Verdict: **APPROVE WITH CHANGES**

The two medium items should be addressed before `terraform apply`:

1. **M1:** Change `--write-kubeconfig-mode 644` to `600` (1-line fix)
2. **M2:** Harmonize EBS validation to `>= 30` in compute module (1-line fix)

The three low items (L1-L3) are recommended for a follow-up PR. None are blocking.

The core architecture decision -- Zero Trust via Tailscale mesh with removal of all public ingress rules -- is sound, well-documented, and represents a significant security improvement. The SOPS integration is correctly configured with matching `encrypted_regex` and AGE keys. The k3s version alignment with existing Pi agents eliminates version skew risk.

---

**Review Completed:** 2026-02-14
**Reviewer:** Tech Lead (claude-opus-4-6)
**Previous Review:** 2026-02-05 (APPROVE WITH CHANGES -- critical issues from that review are resolved)
