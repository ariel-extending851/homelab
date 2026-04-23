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
| 🟠 High | *** init container running as root | Changed to `runAsUser: 1000`, dropped all caps, added `readOnlyRootFilesystem: true`, removed `chown` from init script | `k8s/apps/***/deployment.yaml`, `init-password-configmap.yaml` |

### Documented (accepted risk)

| Component | hostPath | Mitigation |
|---|---|---|
| otel-collector | `/`, `/var/log`, `/var/lib/docker/containers` | `readOnly: true`, non-root |
| node-exporter | `/` | `readOnly: true`, UID 65534 |
| *** | `/dev/net/tun` | `CharDevice` type only, scoped to one device |
| *** setup-storage-job | `/mnt/storage` | UID 1000, `readOnlyRootFilesystem`, TTL cleanup |

### Skipped / deferred

- **Image version pinning** for ***, searxng — deferred to ArgoCD Image Updater (see [`fixes-backlog.md`](fixes-backlog.md))

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

After adding NetworkPolicy isolation to the `media` namespace and attempting to add *** sidecars to additional services (*** alongside ***), the VPN tunnel established but routing failed — `default route` stayed on `eth0` instead of switching to `tun0`. All traffic bypassed the VPN.

### Findings (at the time)

| Service | Status |
|---|---|
| *** | ⚠️ VPN configured, routing broken (IP exposed) |
| *** | ❌ *** added then reverted (couldn't route) |
| *** / *** | ✅ Internal-only — no VPN needed |
| *** | ❌ No VPN (medium risk) |

Suspected root causes (at the time):
1. *** simultaneous-connection limit (4 sidecars exceeded the budget)
2. Multiple pod restarts triggering rate limiting
3. *** routing inside Kubernetes shared network namespace
4. Possible *** server-side block

### What was tried

- *** DNS (193.36.144.130) → broke connectivity
- Cloudflare DNS (1.1.1.1) → still broken
- Removed DNS override → still broken
- Scaled to single VPN sidecar → still broken
- Pod recreations + reverts → still broken

### Resolution (April 2026, post-audit)

The routing problem turned out to be the **IPv6 endpoint resolution** issue (*** resolved *** to an IPv6 address but the Pi has no IPv6 routing). Fixed by:

- Pinning `WIREGUARD_ENDPOINT_IP=193.32.127.66` (IPv4)
- `VPN_IPV6=off`
- Disabling IPv6 on the Pi host (`/etc/sysctl.d/99-disable-ipv6.conf`)

Detail: [`../services/***.md#vpn-endpoint-pinning-ipv4-only`](../services/***.md#vpn-endpoint-pinning-ipv4-only). The ***-account-limit hypothesis was a red herring; the multi-sidecar approach was abandoned in favor of routing only *** through the VPN (the only service that genuinely needs it).

### NetworkPolicy decisions made (still in effect)

| Direction | Rule |
|---|---|
| Ingress | Allow same namespace, kube-system (probes), tailscale namespace (WebUI) |
| Egress | Allow same namespace, kube-system DNS, VPN endpoint, HTTP/HTTPS, *** control port (8000) |

---

## 2026-01-28 — *** Security Review

Source: still lives at [`../reviews/2026-01-28-***-security.md`](../reviews/2026-01-28-***-security.md) (date-prefixed reviews are kept separate as authoritative reference docs).

Outcome: VPN sidecar architecture validated; resource limits sized appropriately for `media` namespace ([`../operations/resource-limits.md`](../operations/resource-limits.md)); naming follows [`../CONVENTIONS.md`](../CONVENTIONS.md).

---

## 2026-01-?? — Container Image Audit

Source: original `CONTAINER_IMAGE_AUDIT.md` (now merged here).

### Audited Images

| App | Image | Pinning | Risk |
|---|---|---|---|
| *** | `lscr.io/linuxserver/***:latest` | `latest` (drift risk) | Medium |
| *** / *** / *** | `lscr.io/linuxserver/<app>:latest` | `latest` | Medium |
| *** | `ghcr.io/***/***:v3.3.6` | Pinned | Low |
| *** | `***/***` | `latest` | Medium |
| grafana | `grafana/grafana` | `latest` | Medium |
| prometheus | `prom/prometheus` | `latest` | Medium |
| loki | `grafana/loki` | `latest` | Medium |
| node-exporter | `prom/node-exporter` | `latest` | Medium |
| kube-state-metrics | `registry.k8s.io/kube-state-metrics/kube-state-metrics` | `latest` | Medium |
| blackbox | `prom/blackbox-exporter` | `latest` | Medium |
| otel-collector | `otel/opentelemetry-collector-contrib` | `latest` | Medium |
| *** | `qmcgaw/***` | `latest` | Medium |
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
