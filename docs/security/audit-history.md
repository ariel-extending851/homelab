# Security Audit History

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Chronological record of security audits, findings, and remediations. The current security posture lives in [`overview.md`](overview.md); open work lives in [`fixes-backlog.md`](fixes-backlog.md).

This page is the historical record — entries here describe the state at the time of each audit, not necessarily today's reality.

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
