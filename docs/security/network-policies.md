# Network Policies & Capability Use

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Documentation of the active Kubernetes NetworkPolicies plus an analysis of the one elevated capability we use (`NET_ADMIN` on the *** sidecar).

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

### `media/media-network-policy` ([`k8s/apps/***/network-policy.yaml`](../../k8s/apps/***/network-policy.yaml))

Scoped policy for the media namespace.

**Ingress allowed:**
- Same namespace (intra-app: *** ↔ *** ↔ *** ↔ ***)
- `kube-system` (kubelet probes)
- `tailscale` namespace (WebUI access on each app's port: 8080, 7878, 8989, 9696, 8191)

**Egress allowed:**
- Same namespace
- `kube-system` port 53 (DNS)
- *** VPN endpoint (193.32.127.66:51820 UDP — pinned IPv4 endpoint)
- HTTP/HTTPS (ports 80, 443) — for tracker announces, app updates, Grafana scrape
- *** control API (port 8000, localhost only)

**Egress denied:** everything else.

Important: the policy allows port 80/443 outbound from the namespace, but **the *** killswitch (in ***) constrains *** specifically to only egress through the VPN tunnel**. The NetworkPolicy is defense in depth, not the only barrier.

---

## Capability Analysis: `NET_ADMIN` on ***

### Question

Does the *** VPN sidecar **strictly require** `NET_ADMIN`, or can it be removed/reduced?

### Answer: **Strictly required.**

`NET_ADMIN` is non-negotiable for ***'s VPN tunnel. Three operations need it:

#### 1. TUN/TAP interface creation

```bash
ip tuntap add dev tun0 mode tun
```

Specifically: `TUNSETIFF` ioctl, interface configuration, MTU settings.

#### 2. Routing table manipulation

```bash
ip route add default via <vpn-gateway> dev tun0
ip route add <local-subnets> via <pod-gateway> dev eth0
```

Add/delete routes (`RTM_NEWROUTE`, `RTM_DELROUTE`), modify default gateway, policy-based routing.

#### 3. iptables firewall (the killswitch)

```bash
iptables -A OUTPUT -o tun0 -j ACCEPT
iptables -A OUTPUT ! -o lo -j DROP
```

Create/modify iptables chains, set firewall rules, NAT/MASQUERADE configuration.

### Mitigations in place

```yaml
# k8s/apps/***/deployment.yaml (*** container)
securityContext:
  capabilities:
    add: ["NET_ADMIN"]              # only this; not all-caps
    drop: ["ALL"]                    # explicit drop of everything else
  runAsUser: 0                       # required for iptables
  allowPrivilegeEscalation: false    # cannot escalate further
```

Plus:
- **Network namespace sharing:** *** shares ***'s netns but does **not** itself have `NET_ADMIN`
- **Filesystem isolation:** *** has no access to ***'s `/data`
- **Resource limits:** 100m CPU / 128Mi memory cap — can't run away even if compromised

### Alternatives considered

| Option | Why we didn't take it |
|---|---|
| Userspace WireGuard (`wireguard-go`) | We already use `WIREGUARD_IMPLEMENTATION=userspace`. It still needs `NET_ADMIN` for routing/iptables. |
| `CAP_NET_RAW` only | Cannot create TUN devices or modify routes. |
| Node-level VPN | Would break the per-pod killswitch and make the NetworkPolicy meaningless. |

### Verification

```bash
# Current capability set
kubectl exec -n media deploy/*** -c *** -- \
  cat /proc/1/status | grep Cap

# Test removal (expected to fail)
kubectl patch deploy *** -n media --type=json \
  -p='[{"op":"remove","path":"/spec/template/spec/containers/0/securityContext/capabilities"}]'
# expect (in *** logs): RTNETLINK answers: Operation not permitted
```

### Future hardening (optional)

```yaml
securityContext:
  capabilities:
    add: ["NET_ADMIN"]
    drop: ["ALL"]
  readOnlyRootFilesystem: true       # not currently set; would prevent FS tampering
  runAsNonRoot: false                 # MUST stay root for iptables
  allowPrivilegeEscalation: false
```

`readOnlyRootFilesystem: true` is the obvious next step — *** doesn't write outside `/tmp` and `/run`. Tracked in [`fixes-backlog.md`](fixes-backlog.md).

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
- ***** VPN architecture:** [`../services/***.md`](../services/***.md)
- **Open backlog:** [`fixes-backlog.md`](fixes-backlog.md)
