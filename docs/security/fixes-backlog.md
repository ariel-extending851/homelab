# Security Fixes Backlog

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Open security work. The 2026-01-31 hardening pass closed all Critical/High items — see [`audit-history.md#2026-01-31--hardening-pass`](audit-history.md#2026-01-31--hardening-pass). What's left is Medium / Low / Quality-of-life work.

---

## Open Items

### 1. Image version pinning (Medium)

**Status:** Deferred (since 2026-01-31)
**Files affected:** ~13 of the 16 deployed apps still use `:latest` tags

**Plan:** install ArgoCD Image Updater and add per-Application annotations to drive automated semver pinning + git write-back for audit.

```yaml
# example annotation set on each ArgoCD Application
metadata:
  annotations:
    argocd-image-updater.argoproj.io/image-list: "***=lscr.io/linuxserver/***"
    argocd-image-updater.argoproj.io/***.update-strategy: "semver"
    argocd-image-updater.argoproj.io/***.allow-tags: "regexp:^[0-9]+\\.[0-9]+\\.[0-9]+"
    argocd-image-updater.argoproj.io/write-back-method: "git:secret:argocd/git-creds"
```

Bootstrap:
```bash
kubectl apply -n argocd -f \
  https://raw.githubusercontent.com/argoproj-labs/argocd-image-updater/stable/manifests/install.yaml
```

**Effort:** ~2 hours (one weekend afternoon).

### 2. Read-only root filesystem on *** (Low)

**Status:** Recommended but not applied
**File:** `k8s/apps/***/deployment.yaml`

*** doesn't write outside `/tmp` and `/run`. Adding `readOnlyRootFilesystem: true` is a small hardening win.

```yaml
securityContext:
  capabilities: { add: [NET_ADMIN], drop: [ALL] }
  runAsUser: 0
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true     # <-- add this
```

Validate by running normally for a week and confirming no unexpected EROFS errors in *** logs.

**Effort:** 30 min (edit + verify + ArgoCD sync).

### 3. Pod Security Admission labels (Low)

**Status:** Not applied (OPA Conftest covers most of the same ground)

Add `pod-security.kubernetes.io/enforce: baseline` (or `restricted` per-namespace) labels to namespaces. Provides defense in depth alongside the existing OPA policies.

Per-namespace mapping (proposed):

| Namespace | Profile |
|---|---|
| `media`, `***`, `searxng` | restricted (*** *** would need an exception) |
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

### 5. Tailscale OAuth token rotation cadence (Quality-of-life)

**Status:** Manual process, no calendar reminder

The Tailscale operator uses an OAuth client. Rotate the secret every ~6 months, document in password manager. Could be automated by re-running the Helm install with new credentials sourced from SOPS.

**Effort:** 15 min one-shot to set up; 5 min every 6 months to rotate.

---

## Recently Closed (cross-reference)

For closed items, see [`audit-history.md`](audit-history.md). Highlights:

- **2026-01-31** — Removed `privileged: true` from otel-collector
- **2026-01-31** — *** init container moved to UID 1000
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
- **Latest review:** [`../reviews/2026-01-28-***-security.md`](../reviews/2026-01-28-***-security.md)
