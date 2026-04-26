# Networking

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Tailscale is the only ingress path. There are no public TCP ports anywhere in the homelab stack.

---

## Address Plan

| CIDR | Purpose | Source |
|---|---|---|
| `192.168.8.0/24` | Home admin LAN (trusted) | `ansible/group_vars/all.yml` |
| `192.168.9.0/24` | Home guest/IoT LAN (isolated) | `ansible/group_vars/all.yml` |
| `192.168.8.1` | Opal gateway (OpenWrt, GL.iNet) | `ansible/group_vars/all.yml` |
| `100.64.0.0/10` | Tailscale CGNAT range, per-node IPs | Tailscale console |
| `tail57bf10.ts.net` | MagicDNS suffix for the tailnet | Tailscale console |
| `10.42.0.0/16` | k3s **pod** CIDR (Flannel VXLAN) | `ansible/group_vars/all.yml` |
| `10.43.0.0/16` | k3s **service** CIDR (ClusterIP) | `ansible/group_vars/all.yml` |
| `cluster.local` | k3s cluster DNS suffix | `ansible/group_vars/all.yml` |

---

## Tailscale Mesh

Every node runs the Tailscale daemon (Ansible `tailscale` role) and joins the tailnet using an auth key delivered via SOPS. WireGuard handles the encryption; ACLs are managed in the Tailscale admin console (not in this repo).

**Why Tailscale:**

- Zero public attack surface — no SSH or k3s API exposed to the internet
- Operator laptop joins the same mesh and reaches every node by hostname
- Cross-cloud-and-LAN flat addressing (AWS instances and Raspberry Pi nodes are peers)

**Operational notes:**
- Auth keys are reusable + ephemeral; rotated periodically
- Stale tailnet nodes are pruned with `make clean-tailscale` (Ansible playbook calling the Tailscale API)
- Recovery when nodes drop off: [`../runbooks/tailscale-logged-out.md`](../runbooks/tailscale-logged-out.md)

---

## Ingress: Tailscale Operator

Inside the cluster, the **Tailscale Kubernetes operator** ([`k8s/system/tailscale-operator`](../../k8s/system/tailscale-operator)) provides an `IngressClass` named `tailscale`. Any `Ingress` resource using that class gets:

- A dedicated proxy pod (`ts-<name>` in the `tailscale` namespace)
- A tailnet hostname matching the Ingress `host`
- Automatic TLS via Tailscale's managed certificate program
- No external load balancer, no Cloudflare tunnel, no port forwarding

Active ingress hostnames are tracked in [`../reference/tailnet-services.md`](../reference/tailnet-services.md).

### Proxy Classes

The operator supports `ProxyClass` resources to shape traffic per-Service. The repo defines:

| ProxyClass | Used by | Purpose |
|---|---|---|
| `default` | most apps | Standard bandwidth, single replica |
| `high-bandwidth` | grafana | Larger CPU/mem requests for dashboard/log streaming |

To use, label the `Service`: `tailscale.com/proxy-class: high-bandwidth`.

---

## Proxy Distribution Across Raspberry Pis

Earlier analysis ([`docs/analysis/rpi4-proxy-audit.md`](../analysis/rpi4-proxy-audit.md)) noted that running every Tailscale proxy pod on a single Pi causes load imbalance. Current placement strategy:

- **rasp-pi-03** (1 GB RPi 3): hosts only lightweight proxies (SearXNG and the monitoring sidecars)
- **AWS nodes**: host the rest

Placement is driven by `nodeSelector` / `nodeAffinity` in each app's `deployment.yaml`.

---

## Kubernetes NetworkPolicies

Most app namespaces are open. The two enforced policies live in [`k8s/system/network-policies/monitoring-policies.yaml`](../../k8s/system/network-policies/monitoring-policies.yaml):

- **Allow Prometheus scrape** from the `monitoring` namespace into all app namespaces (TCP on each app's metrics port)
- **Default-deny** for the `monitoring` namespace's egress to anything other than DNS, intra-cluster scrape targets, and Loki

---

## Operator Access Paths

There are exactly two ways to reach a node:

1. **Tailscale (preferred)**: `ssh <user>@<node>.tail57bf10.ts.net`. Works for AWS instances and RPis identically.
2. **AWS SSM Session Manager (break-glass)**: `aws ssm start-session --target <instance-id>`. IAM-authenticated, audit-logged in CloudTrail. Used when a node has joined AWS but not yet joined the tailnet (initial bootstrap, or after a failed Tailscale auth).

There is **no inbound SSH from the internet to the AWS instances.** The `infra/aws/modules/network` security group has no `0.0.0.0/0` rule.

---

## Where to Go Next

- **Tailscale operator details:** [`../services/tailscale-operator.md`](../services/tailscale-operator.md)
- **Recovery when tailnet auth fails:** [`../runbooks/tailscale-logged-out.md`](../runbooks/tailscale-logged-out.md)
- **Per-app ingress hostnames:** [`../reference/tailnet-services.md`](../reference/tailnet-services.md)
- **AWS infra (security group rules):** [`aws-infrastructure.md`](aws-infrastructure.md)
