# Network Policies & Capability Use

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

---

## Active NetworkPolicies

### `monitoring/monitoring-policies` ([`k8s/system/network-policies/monitoring-policies.yaml`](../../k8s/system/network-policies/monitoring-policies.yaml))

Cluster-wide policy for the monitoring namespace.

**Egress allowed:**
- DNS to `kube-system` (port 53 UDP/TCP)
- Scrape targets in app namespaces (whatever metrics port each app exposes)
- Loki at `loki.loki:3100` (for Promtail/OTEL pushes)

**Egress denied:** everything else (default-deny on egress).

This stops a compromised exporter from exfiltrating data anywhere it likes.

> **Historical note (2026-05-01):** Earlier revisions of this doc described a `media` namespace policy and a VPN sidecar (`NET_ADMIN`) used by the *arr/SearXNG stack. That stack was removed in commit `39b0e67` and the related sections have been deleted to keep the doc accurate. If a future stack needs `NET_ADMIN`, document the cap justification, killswitch, and `dropAll` block here.

---

## Other Elevated Capabilities

| Container | Capability | Why |
|---|---|---|
| AdGuard | `NET_BIND_SERVICE`, `SETUID`, `SETGID` | Bind to port 53; init-time user switching to nobody (UID 65534) |
| Tailscale operator + sidecars | `NET_RAW` (some configurations) | Userspace networking — lower risk |

All other containers run with `capabilities: { drop: [ALL] }`.

---

## Why we don't use Pod Security Admission (yet)

Kubernetes 1.25+ has built-in Pod Security Admission with restricted/baseline/privileged labels per namespace. We rely on **OPA Conftest** in CI instead:

- [`k8s/policies/security_context.rego`](../../k8s/policies/security_context.rego) — `allowPrivilegeEscalation: false` required
- [`k8s/policies/resource_limits.rego`](../../k8s/policies/resource_limits.rego) — CPU + memory limits required
- [`k8s/policies/health_probes.rego`](../../k8s/policies/health_probes.rego) — readinessProbe required
- [`k8s/policies/rbac_safety.rego`](../../k8s/policies/rbac_safety.rego) — no wildcard verbs/resources

Pre-deployment enforcement is preferred over admission-time rejection in our workflow (faster feedback in PR review). Adding PSA is on the [`fixes-backlog.md`](fixes-backlog.md) but not urgent.

---

## Related

- **Security overview:** [`overview.md`](overview.md)
- **Audit history:** [`audit-history.md`](audit-history.md)
- **Open backlog:** [`fixes-backlog.md`](fixes-backlog.md)
