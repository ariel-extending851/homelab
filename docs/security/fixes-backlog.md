# Security Fixes Backlog

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Open security work. The 2026-01-31 hardening pass closed all Critical/High items — see [`audit-history.md#2026-01-31--hardening-pass`](audit-history.md#2026-01-31--hardening-pass). What's left is Medium / Low / Quality-of-life work.

---

## Open Items

### 1. Image version pinning + CVE-driven upgrades (Medium)

**Status:** In progress — see [Image Upgrade Sprint 2026 Q3 runbook](../runbooks/image-upgrade-sprint-2026-q3.md). Target completion 2026-07-30 (matches `.trivy-image-allowlist.txt` review-by date).
**Files affected:** ~13 of the 16 deployed apps still use `:latest` tags

**Plan:** install ArgoCD Image Updater and add per-Application annotations to drive automated semver pinning + git write-back for audit.

```yaml
# example annotation set on each ArgoCD Application
metadata:
  annotations:
    argocd-image-updater.argoproj.io/write-back-method: "git:secret:argocd/git-creds"
```

Bootstrap:
```bash
kubectl apply -n argocd -f \
  https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/manifests/install.yaml
```

**Effort:** ~2 hours (one weekend afternoon).

**Status:** Recommended but not applied

```yaml
securityContext:
  capabilities: { add: [NET_ADMIN], drop: [ALL] }
  runAsUser: 0
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true     # <-- add this
```

**Effort:** 30 min (edit + verify + ArgoCD sync).

### 3. Pod Security Admission labels (Low)

**Status:** Not applied (OPA Conftest covers most of the same ground)

Add `pod-security.kubernetes.io/enforce: baseline` (or `restricted` per-namespace) labels to namespaces. Provides defense in depth alongside the existing OPA policies.

Per-namespace mapping (proposed):

| Namespace | Profile |
|---|---|
| `monitoring`, `loki`, `grafana`, `otel-collector` | restricted |
| `tailscale` | privileged (operator needs broad permissions) |
| `argocd`, `kube-system` | privileged |
| `adguard` | baseline (NET_BIND_SERVICE for port 53) |
| `golink` | restricted |

**Effort:** ~1 hour to label and verify nothing breaks.

### 4. SBOM + image vulnerability gating (Low)

**Status:** `make test-security-supply-chain` runs but doesn't gate

Currently the supply-chain test reports findings; nothing fails the build. Plan: tighten so high-severity CVEs in deployed image versions block PRs.

Tooling already pinned: see [`.mise.toml`](../../.mise.toml). The gate would be a CI check that grep's the supply-chain report for `severity: HIGH|CRITICAL` and exits non-zero.

**Effort:** ~1 hour.

### 5. CloudTrail customer-managed KMS key (Low)

**Status:** Deferred — flagged by `trivy config` (`AVD-AWS-0015`) and currently allowlisted in `.trivyignore.yaml` (expires 2026-12-31).

**File:** `infra/aws/modules/audit/main.tf:135-153`

CloudTrail is encrypted at rest by an AWS-managed KMS key. AVD-AWS-0015 recommends a customer-managed CMK so we own the key policy + rotation cadence.

**Trade-off:**
- Cost: ~$1/month for the CMK + per-call fees on audit log writes
- Benefit: separation of duties (KMS policy ≠ S3/CloudTrail policy), explicit rotation policy, ability to revoke
- Acceptance: AWS-managed key already provides at-rest encryption; the homelab does not have a compliance regime (PCI/SOC2) that mandates CMK.

**Plan when needed:**
1. Add `aws_kms_key` resource with `enable_key_rotation = true` and a key policy granting CloudTrail.
2. Reference it via `kms_key_id` on the trail.
3. Migrate existing log objects (re-encrypt) — Velero/CloudTrail copy semantics out of scope here.

**Effort:** ~45 min including tflint + terraform plan review.

### 6. Tailscale OAuth token rotation cadence (Quality-of-life)

**Status:** Manual process, no calendar reminder

The Tailscale operator uses an OAuth client. Rotate the secret every ~6 months, document in password manager. Could be automated by re-running the Helm install with new credentials sourced from SOPS.

**Effort:** 15 min one-shot to set up; 5 min every 6 months to rotate.

---

## Recently Closed (cross-reference)

For closed items, see [`audit-history.md`](audit-history.md). Highlights:

- **2026-01-31** — Removed `privileged: true` from otel-collector
- **2026-01-31** — All hostPath mounts documented and secured
- **2026-04** (during docs consolidation) — Repo URL OIDC trust policy mismatch flagged for cleanup ([`../architecture/aws-infrastructure.md#bootstrap-modules-aws-backend-aws-oidc`](../architecture/aws-infrastructure.md#bootstrap-modules-aws-backend-aws-oidc))

---

## How to Add an Item

Append a numbered section here with:

- **Status** (Open / Deferred / In progress)
- **File(s) affected** with line numbers when relevant
- **Plan** (concrete steps, not aspiration)
- **Effort estimate** (be honest)

When closed, move the entry's summary to [`audit-history.md`](audit-history.md) under a date heading and remove it from this file.

---

## Related

- [`overview.md`](overview.md) — current security posture
- [`audit-history.md`](audit-history.md) — chronological record (closed items)
- [`network-policies.md`](network-policies.md) — NetworkPolicy + capability detail
