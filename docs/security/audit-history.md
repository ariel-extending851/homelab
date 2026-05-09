# Security Audit History

> **Status:** Active
> **Last reviewed:** 2026-05-09
> **Owner:** @ariel-extending851

Chronological record of security audits, findings, and remediations. The current security posture lives in [`overview.md`](overview.md); open work lives in [`fixes-backlog.md`](fixes-backlog.md).

This page is the historical record — entries here describe the state at the time of each audit, not necessarily today's reality.

---

## 2026-05-09 — AdGuard Home: runAsUser 65534 → 0 (incident-driven)

Triggered by an incident (`/incident`) on the production cluster: `adguard/adguardhome-*` in CrashLoopBackOff with **141 restarts over 23h**, exit code 1 inside the same wall-clock second. Logs showed AdGuard's first-launch permcheck rejecting the non-root container with `you must run it as administrator`.

### Decision

Pod-level `securityContext` changed from `runAsUser: 65534 / runAsGroup: 65534 / fsGroup: 65534` to `runAsUser: 0 / runAsGroup: 0` (drop `fsGroup`). Container caps add `NET_RAW` alongside `NET_BIND_SERVICE`.

### Why root is acceptable here

AdGuard Home v0.107.50+ permcheck inspects the **binary's file capabilities** (`cap.GetFile`), not the **process** caps injected by the Pod. The upstream image ships without `setcap` on the binary, so non-root + Pod-level `NET_BIND_SERVICE` still fails the check. Upstream's official k8s example also runs as root.

The pod already requires `hostNetwork: true` to bind UDP/TCP 53 on the node — that alone makes the runtime co-tenant with the host's network namespace. Dropping `runAsUser: 65534` does not change the pod's blast radius materially in this configuration.

### Mitigations retained

- `privileged: false`
- `allowPrivilegeEscalation: false` (`no_new_privs` on the process)
- `capabilities.drop: [ALL]` then explicit add of `NET_BIND_SERVICE`, `NET_RAW`, `SETUID`, `SETGID`
- NetworkPolicy `default-deny` + `allow-adguardhome` egress allowlist (added 2026-05-07 in PR-E)
- Single-namespace, single-pod scope; no service account binding outside its namespace
- Read-only mount for the docs ConfigMap

### Hardening deferred

- Init-container `setcap` workaround to allow non-root, once upstream stabilizes
- `nodeSelector: role=dns-server` for IP-stability of the DNS endpoint

Linked runbook: [`docs/runbooks/adguard-firstlaunch-permcheck.md`](../runbooks/adguard-firstlaunch-permcheck.md).

Same-PR cleanup: deleted `k8s/apps/adguard/pv.yaml` (storageClassName mismatched the PVC; pinned to a node that has not existed in the cluster since the 2026-05-04 re-deploy). Dynamic `local-path` provisioning has covered this PVC since first deploy.

---

## 2026-05-07 — Dependabot-Simulation Audit (Supply Chain Pass)

Source: branch `worktree-calm-oak-vk48`, plan file `/home/vscode/.claude/plans/role-you-are-a-vast-pascal.md`. Read-only audit across Python deps, GitHub Actions, Terraform providers, Ansible collections, k8s manifests, RBAC, security contexts, and SAST on Python/Terraform/Ansible.

### Headline

No critical RCE / IAM-bypass / secret-exposure issues. Bulk of the work is supply-chain hygiene — pinning, allowlist tracking, and segmentation — not bug-fixing.

### Fixed in this pass (PRs A/B/C/D/E/F/G/H/I)

| Risk | Item | Resolution | Files |
|---|---|---|---|
| 🔴 Critical | 52+ floating GitHub Action refs (`@v3/v4/v5/v7`) — supply-chain takeover | Pinned every `uses:` to a 40-char commit SHA across 10 workflows; tag retained as trailing comment so Dependabot can keep them current weekly. Pinned to latest patch within current major (no major bumps). 97 ref lines updated. | `.github/workflows/*.yml` (10 files) |
| 🟠 High | CI pip installs unpinned (`pytest pytest-cov pyyaml jinja2 boto3`) | Added `[project.optional-dependencies] ci` with explicit floors (jinja2 ≥ 3.1.6 → CVE-2024-34064; urllib3 ≥ 2.5.0 → CVE-2024-37891 transitive) | `pyproject.toml`, `.github/workflows/ci-validation.yml` |
| 🟠 High | Ansible collections with no upper bound (`>=3.0.0`) | Added `<major+1` upper bounds on `kubernetes.core`, `community.sops`, `community.general`, `ansible.posix` to protect 1 GB RPi3 from transitive-dep churn during converges | `ansible/requirements.yml` |
| 🟠 High | Floating tool versions in `.mise.toml` (`terraform`, `kubectl`, `awscli`, `sops`, `jq`, `tflint`, `infracost`, `actionlint`, `pre-commit`, `zizmor`) | Pinned each to a known version. `kubectl 1.30.14` matches k3s server minor; `terraform 1.11.0` matches CI workflow pin. LocalStack pipx tools left at `latest` (continue-on-error job only). | `.mise.toml` |
| 🟠 High | 10 namespaces missing NetworkPolicy (adguard, blackbox, falco, golink, kube-state-metrics, node-exporter, otel-collector, storage-latency, unifi, velero) | Added `default-deny` (Ingress + Egress) plus tight per-workload allow-list per namespace. 21 NetworkPolicy resources total; validated with kubeconform + kustomize build. hostNetwork pods get best-effort ingress under most CNIs (egress rules apply since they're pod-scoped). | `k8s/apps/<ns>/networkpolicy.yaml` (10 new) + each `kustomization.yaml` |
| 🟡 Medium | Dependabot missing `docker` ecosystem | Added `package-ecosystem: docker` block (npm deferred — no `package.json` yet) | `.github/dependabot.yml` |
| 🟡 Medium | Terraform state-lock table missing at-rest encryption + PITR (3× tfsec ignores acknowledged but not fixed) | Added `point_in_time_recovery { enabled = true }` and `server_side_encryption { enabled = true }`; left CMK ignore in place with rationale comment | `infra/aws-backend/main.tf` |
| 🟡 Medium | 15 image refs missing `@sha256:` digest pin | Resolved manifest-list digests via `crane digest` and appended `@sha256:<digest>` to 17 image refs across 14 files. ARM64-safe: pinned manifest lists, not arch leaves, so K8s resolves per-arch digest at pull time. | `k8s/apps/**/*.yaml` (13 files) + `k8s/gitops/sops/argocd-repo-server-patch.yaml` |
| 🟢 Low | `link-checker.yml` missing top-level `permissions:` | Added `permissions: { contents: read }` (bundled with PR-A SHA pins after zizmor flagged the gap on the SHA-pinned diff) | `.github/workflows/link-checker.yml` |

### Residual risk register (action required by review-by date)

| # | Risk | Class | Owner | Review-by | Notes |
|---|---|---|---|---|---|
| 1 | `anthropics/claude-code-action@v1.0.115` (third-party, holds `id-token: write`) | action-takeover | @ariel-extending851 | 2026-08-01 | SHA-pinned in PR-A but the trust decision is residual; re-evaluate quarterly. Used in `claude-code-review.yml:35`, `claude.yml:43` |
| 2 | `tailscale/tailscale ~> 0.13` Terraform provider | third-party-provider | @ariel-extending851 | 2026-08-01 | Re-verify maintenance status quarterly; consider patch-pinning |
| 3 | `.trivy-image-allowlist.txt` — 13 known-CVE images allowlisted | image-cve | @ariel-extending851 | 2026-07-30 | Driven by `docs/runbooks/image-upgrade-sprint-2026-q3.md`; do not let dates silently expire |
| 4 | Velero ClusterRole `verbs/apiGroups/resources = ["*"]` | rbac-overly-broad | @ariel-extending851 | 2026-08-01 | Documented exception in `k8s/policies/rbac_safety.rego`; quarterly RBAC review |

### Posture delta

| Before | After |
|---|---|
| CRITICAL: 52+ floating action refs (mid-week supply-chain takeover risk) | All workflows SHA-pinned + Dependabot keeps current |
| HIGH: CI test toolchain auto-pulls latest (CVE exposure window) | Pinned in `pyproject.toml` `[ci]` extra |
| HIGH: Ansible major-bump risk on RPi3 | Capped at current major across all 4 collections |
| HIGH: Tool drift between local + CI (kubectl/k3s minor mismatch class of failure) | `.mise.toml` pinned to k3s-matched versions |
| HIGH: 10 NS with no network segmentation | Default-deny + minimal allow per NS |
| MEDIUM: Container-image bumps tracked manually via Trivy allowlist | Dependabot now opens weekly PRs |
| MEDIUM: State-lock table unencrypted at rest | SSE + PITR enabled |
| MEDIUM: 15 image refs mutable (registry-replay vulnerable) | Manifest-list digests pinned |
| LOW: link-checker workflow ran with default permissions | Restricted to `contents: read` |

Overall risk: **CRITICAL/HIGH → LOW** (4 residuals are policy/quarterly-review items, not code gaps).

### Known follow-up CI behaviour (PR #66)

| Symptom | Class | Why | Action |
|---|---|---|---|
| `claude-review` workflow fails on this PR with `App token exchange failed: 401 — Workflow validation failed` | expected | The `anthropics/claude-code-action` action refuses to issue a PR-scoped token when the workflow file on the PR diverges from `develop`. PR-A SHA-pinned the action, so divergence is by design. The action's own error message instructs to ignore on first-add. | Resolves automatically once the PR merges to `develop`; the action then runs identically against the new SHA. No code change. |
| `Trivy strict` failed initial run on PR #66 | regression-from-this-pass | PR-H added `@sha256:…` digests to manifest `image:` refs; `bin/trivy_scan.py` did exact-string allowlist matching, so digest-suffixed refs missed entries. | Fixed in follow-up commit: `bin/trivy_scan.py` now also matches the bare `repo:tag` form. |
| `QA: Offline Required Profile` failed on `oidc.tftest.hcl:110` with `contains() argument must be list`; second iteration failed on `backend.tftest.hcl` teardown with `aws_s3_bucket.terraform_state has lifecycle.prevent_destroy set` | regression-from-this-pass | PR-E pinned `terraform = "1.11.0"` (was `latest` ≈ 1.15.x). 1.11 has two test-framework behaviors that 1.15 doesn't: (a) `&&` evaluates eagerly in `for` expressions, so `contains(try(stmt.Action, []), …)` fires even on filtered-out `Allow` statements (homelab_principal_boundary has `Action = "*"` scalar that breaks `contains`); (b) `prevent_destroy` is enforced during mock_provider teardown of resources not under test, blocking S3 bucket destruction even though the test is mocked. | Fixed in two follow-up commits: (1) wrap `try(stmt.Action, [])` in `flatten([...])` at all 7 call-sites in `infra/aws-oidc/tests/oidc.tftest.hcl` for type-tolerance — this is defensive and correct on any terraform version; (2) bump `.mise.toml` `terraform = "1.15.2"` to match what develop's CI implicitly used. CI-only setup-terraform pin in `ci-validation.yml` (`terraform_version: "1.11.0"`) stays — that job only runs `terraform plan`, no tests, so the cross-job mismatch is cosmetic. |
| `Kubernetes: GitOps Convergence (k3d)` flaked on push of fix commit (`ComparisonError: dial tcp 10.43.169.177:8081: connect: connection refused`) | flake | The first CI run on this branch (with all 9 PRs and the digest pins) passed k3d in 1m11s; the failing run was the rebuild after pushing the fix commit, which only changed `bin/trivy_scan.py`, `infra/aws-oidc/tests/oidc.tftest.hcl`, and this doc. None of those affect ArgoCD repo-server bootstrap. Connection refused on a cluster service IP indicates the repo-server pod hadn't fully started when the test polled. | No fix needed unless it persists. The `k3d_convergence.py` test treats any `ComparisonError` as fatal, which is a known sharp edge. If it recurs on retries, follow up by adding a startup-grace retry on transient gRPC unavailable. |

---

## 2026-01-31 — Hardening Pass

Source: original `SECURITY_FIX_PLAN.md` (now merged here).

### Fixed

| Risk | Item | Resolution | Files |
|---|---|---|---|
| 🔴 Critical | otel-collector running with `privileged: true` | Switched to `privileged: false`, added `runAsUser: 0` + `allowPrivilegeEscalation: false` + drop ALL capabilities + `readOnlyRootFilesystem: true` | `k8s/apps/otel-collector/daemonset.yaml` |

### Documented (accepted risk)

| Component | hostPath | Mitigation |
|---|---|---|
| otel-collector | `/`, `/var/log`, `/var/lib/docker/containers` | `readOnly: true`, non-root |
| node-exporter | `/` | `readOnly: true`, UID 65534 |

### Skipped / deferred

### Posture delta

| Before | After |
|---|---|
| CRITICAL: full host compromise possible via privileged container | None — privileged: false enforced |
| HIGH: root access during pod init | Init runs as UID 1000 |
| HIGH: unsecured hostPath mounts | All readOnly or constrained |
| MEDIUM: unpredictable image updates | Pending image updater |

Overall risk: **CRITICAL/HIGH → MEDIUM/LOW**.

---

## 2026-01-30 — Media Stack Assessment (VPN routing)

Source: original `SECURITY_ASSESSMENT.md` (now merged here).

### Context

### Findings (at the time)

| Service | Status |
|---|---|

Suspected root causes (at the time):
2. Multiple pod restarts triggering rate limiting

### What was tried

- Cloudflare DNS (1.1.1.1) → still broken
- Removed DNS override → still broken
- Scaled to single VPN sidecar → still broken
- Pod recreations + reverts → still broken

### Resolution (April 2026, post-audit)

- Pinning `WIREGUARD_ENDPOINT_IP=193.32.127.66` (IPv4)
- `VPN_IPV6=off`
- Disabling IPv6 on the Pi host (`/etc/sysctl.d/99-disable-ipv6.conf`)

### NetworkPolicy decisions made (still in effect)

| Direction | Rule |
|---|---|
| Ingress | Allow same namespace, kube-system (probes), tailscale namespace (WebUI) |

---

Outcome: VPN sidecar architecture validated; resource limits sized appropriately for `media` namespace ([`../operations/resource-limits.md`](../operations/resource-limits.md)); naming follows [`../CONVENTIONS.md`](../CONVENTIONS.md).

---

## 2026-01-?? — Container Image Audit

Source: original `CONTAINER_IMAGE_AUDIT.md` (now merged here).

### Audited Images

| App | Image | Pinning | Risk |
|---|---|---|---|
| grafana | `grafana/grafana` | `latest` | Medium |
| prometheus | `prom/prometheus` | `latest` | Medium |
| loki | `grafana/loki` | `latest` | Medium |
| node-exporter | `prom/node-exporter` | `latest` | Medium |
| kube-state-metrics | `registry.k8s.io/kube-state-metrics/kube-state-metrics` | `latest` | Medium |
| blackbox | `prom/blackbox-exporter` | `latest` | Medium |
| otel-collector | `otel/opentelemetry-collector-contrib` | `latest` | Medium |
| tailscale | `tailscale/tailscale` | `latest` | Medium |
| searxng | `searxng/searxng` | `latest` | Medium |
| adguard | `adguard/adguardhome` | `latest` | Medium |
| golink | `tailscale/golink` | `latest` | Medium |

### Recommendation (still pending — see backlog)

Adopt **ArgoCD Image Updater** for semver-pinned automated updates. Annotations on each Application would specify the update strategy (`semver`, `digest`, or `latest`) and write back to git for audit.

---

## How to Add an Audit Entry

Each entry follows: date, source, findings (table), resolution, posture delta. Append at the top (newest first). For substantive new audits, also create a date-prefixed file under [`../reviews/`](../reviews/) and link to it here.

## Related

- **Current posture:** [`overview.md`](overview.md)
- **Open work:** [`fixes-backlog.md`](fixes-backlog.md)
- **NetworkPolicy detail:** [`network-policies.md`](network-policies.md)
- **Reviews directory:** [`../reviews/`](../reviews/)
