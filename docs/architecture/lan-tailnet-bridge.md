# LAN ↔ Tailnet Bridge

> **Status:** Active
> **Last reviewed:** 2026-05-10
> **Owner:** @ariel-extending851

How LAN clients **without Tailscale installed** (smart TVs, IoT, consoles, guest devices, anything that can't or shouldn't run the Tailscale daemon) reach `*.tail57bf10.ts.net` services.

## Why this doc exists

The default homelab assumption is "every consumer of `*.tail57bf10.ts.net` is on the tailnet" — the user's laptop has the Tailscale client, MagicDNS resolves the hostname directly to a `100.x.y.z` address, and Tailscale routes the packet via the encrypted mesh.

That breaks for two classes of device on the home LAN (`192.168.8.0/24`):

- **Can't run Tailscale at all** — most smart TVs, set-top boxes, game consoles, IoT
- **Shouldn't run Tailscale** — guest devices and anything where installing a VPN client is undesirable

The router itself (GL.iNet Opal SFT1200) is also unable to bridge for them: OpenWrt on this hardware doesn't have the headroom for `tailscaled`. So the LAN-to-tailnet bridge has to live elsewhere.

## End-to-end flow

```text
                                     ┌────────────────────────────┐
                                     │  GL.iNet Opal (192.168.8.1)│
                                     │  ─ no Tailscale            │
                                     │  ─ DNAT :53 lan → AdGuard  │
                                     │  ─ static route            │
                                     │    100.64.0.0/10 → .11     │
                                     └──────┬─────────────────────┘
                                            │
   ┌──────────────────┐                     │            ┌──────────────────────────┐
   │  LAN client      │                     │            │  rasp-pi-03 (192.168.8.12)│
   │  ─ no Tailscale  │  1. dig adguard.    │            │  AdGuard hostNetwork :53  │
   │  ─ DHCP DNS=.1   │     tail57bf10      │            │  upstream split-DNS:      │
   │                  │     .ts.net         │            │   [/tail57bf10.ts.net/]   │
   │                  │ ──────────────────────────────►  │     100.100.100.100       │
   │                  │                     │            │   (others) Cloudflare DoH │
   │                  │ ◄────────────────── 2. 100.x.y.z │                          │
   │                  │     answer          │            └──────────────────────────┘
   │                  │                     │
   │                  │ 3. TCP 443 to       │
   │                  │    100.x.y.z        │
   │                  │ ──────────────────► route 100.64/10 hit
   │                  │                     │            ┌──────────────────────────┐
   │                  │                     │            │  rasp-pi-04 (192.168.8.11)│
   │                  │                     └──────────► │  Tailscale subnet router  │
   │                  │                                  │  + exit node              │
   │                  │                                  │  advertise 192.168.8.0/24 │
   │                  │                                  └─────────┬────────────────┘
   │                  │                                            │
   │                  │                                            │ via tailnet (WG)
   │                  │                                            ▼
   │                  │                                  ┌──────────────────────────┐
   │                  │                                  │  ts-adguard-ingress-…    │
   │                  │                                  │  Tailscale proxy pod     │
   │                  │                                  │  (rasp-pi-04, ts-namespace)│
   │                  │                                  └─────────┬────────────────┘
   │                  │                                            │
   │                  │                                            │ Service ClusterIP
   │                  │                                            ▼
   │                  │                                  ┌──────────────────────────┐
   │                  │                                  │  AdGuard backend pod     │
   │                  │                                  │  (rasp-pi-03, hostNet :80)│
   └──────────────────┘                                  └──────────────────────────┘
```

## Components in the path

| Component | Where | What it does | Source of truth |
|---|---|---|---|
| LAN DNS DNAT | GL.iNet `firewall.dns_hijack_adguard` | Redirects every LAN `:53` query to `pi_adguard_ip:53` so AdGuard sees all DNS traffic, regardless of what the client thinks its resolver is | [`ansible/roles/gatekeeper/tasks/main.yml`](../../ansible/roles/gatekeeper/tasks/main.yml) (~line 248) |
| AdGuard split DNS | rasp-pi-03 `:53` (hostNetwork) | Upstream DNS list with the per-domain prefix `[/tail57bf10.ts.net/]100.100.100.100` — that prefix tells AdGuard "for this domain only, use Tailscale MagicDNS as upstream" | AdGuard Home UI → Settings → DNS → Upstream DNS servers (persisted in PV `/opt/adguardhome/conf/AdGuardHome.yaml`) |
| Tailscale MagicDNS | `100.100.100.100` (Tailscale-managed) | Resolves tailnet hostnames to `100.x.y.z` CGNAT addresses | Tailscale admin console |
| Reverse route | GL.iNet `network.tailscale_reverse_route` | Static route: `100.64.0.0/10` → `pi_tailscale_ip` (LAN gateway). LAN clients sending packets to `100.x` addresses get them forwarded to the subnet router | [`ansible/roles/gatekeeper/tasks/main.yml`](../../ansible/roles/gatekeeper/tasks/main.yml) (~line 196) |
| Subnet router + exit node | rasp-pi-04 (`192.168.8.11`) | Runs `tailscale set --advertise-routes=192.168.8.0/24 --advertise-exit-node`. Receives `100.x` packets from the LAN via the reverse route and forwards them through the tailnet | [`ansible/roles/tailscale/tasks/main.yml:60-71`](../../ansible/roles/tailscale/tasks/main.yml) — gated `when: inventory_hostname == 'rasp-pi-04'` |
| Tailscale ingress proxy | `ts-<app>-ingress-…` pod in `tailscale` namespace | Terminates the tailnet TLS connection, forwards to the Service backend | [`k8s/system/tailscale-operator/`](../../k8s/system/tailscale-operator) ProxyClass `default` (and `high-bandwidth`) pin proxies to rasp-pi-04 |

## Failure modes

| What fails | Symptom | Recovery |
|---|---|---|
| AdGuard pod down | All DNS via failover; `*.ts.net` returns NXDOMAIN (public DNS doesn't know it). Public lookups still work via Mullvad/Quad9/Cloudflare/Google. | `gatekeeper`'s `adguard-failover` cron (1×/min) auto-detects up; restores DNAT + dnsmasq within ≤2 min. See [`gatekeeper` role](../../ansible/roles/gatekeeper/tasks/main.yml) lines ~330–410. |
| rasp-pi-04 down | DNS resolves to `100.x` but the packet dies in the reverse route — no subnet router answering. Nothing on the LAN can reach tailnet IPs. | No failover (single subnet router by design — Pi 3 has 100 Mbps USB-bottlenecked Ethernet vs Pi 4's true Gigabit, see [`docs/services/adguard.md`](../services/adguard.md) deployment notes). Manual: bring rasp-pi-04 back, or temporarily promote another node by re-running `ansible/roles/tailscale` against it with the subnet-router `when:` lifted. |
| GL.iNet down | LAN itself is down — no DNS, no internet. Out of scope of this bridge. | OpenWrt rescue / power-cycle. |
| `pi_tailscale_ip` mismatch | Reverse route gateway points to a non-existent host → packets to `100.x` are black-holed at the router. **This was the state before 2026-05-10** (default was `192.168.8.10`, no host at that IP). | Fixed in [`ansible/roles/gatekeeper/defaults/main.yml`](../../ansible/roles/gatekeeper/defaults/main.yml) — pinned to `.11`. Re-run `make ansible-router` to reconcile the GL.iNet's UCI config. |

## When to install Tailscale on the client vs use this bridge

Use this bridge when the client **cannot or should not** run Tailscale:

| Client | Recommendation | Why |
|---|---|---|
| Smart TV, console, IoT | Bridge (this doc) | No Tailscale binary available on the platform |
| Guest device | Bridge (this doc) | Don't put guests on the personal tailnet |
| Personal laptop / phone | Install Tailscale | MagicDNS direct, ACLs per-device, works off-LAN, lower latency (no extra hop through subnet router) |
| Headless ops box on LAN | Install Tailscale | Same as above, plus tailnet SSH integration |

The bridge is a fallback for devices the operator doesn't fully control. For everything else, native Tailscale is strictly better.

## Configuration reference

### One-time AdGuard split-DNS rule (manual, persisted in PV)

1. Open `https://adguard.tail57bf10.ts.net/#dns` (from any tailnet-connected device).
2. Under **Upstream DNS servers**, add the line (preserving existing lines):
   ```text
   [/tail57bf10.ts.net/]100.100.100.100
   ```
3. Click **Apply**, then **Test upstreams** — should return success.
4. Verify from a non-tailnet LAN client:
   ```bash
   dig @192.168.8.12 adguard.tail57bf10.ts.net  # should return a 100.x.y.z, not NXDOMAIN
   dig @192.168.8.12 google.com                 # unchanged, still answered via the public upstream
   ```

This is intentionally NOT GitOps — AdGuard Home doesn't support partial config files, so the source of truth for `upstream_dns` is the PV (`/opt/adguardhome/conf/AdGuardHome.yaml`) maintained by AdGuard itself. A future GitOps option would be an Ansible task that PATCHes `/control/dns_config` via the AdGuard HTTP API on each deploy; not implemented yet.

### `pi_tailscale_ip` (Ansible)

Set in [`ansible/roles/gatekeeper/defaults/main.yml`](../../ansible/roles/gatekeeper/defaults/main.yml). Must equal the LAN IP of the host that runs the Tailscale subnet router. Today: `192.168.8.11` (rasp-pi-04).

If the subnet-router host moves, update both this default **and** the `inventory_hostname` guard in [`ansible/roles/tailscale/tasks/main.yml:60-71`](../../ansible/roles/tailscale/tasks/main.yml), then re-run `make ansible-deploy` for the Pi role and `make ansible-router` for the GL.iNet.

### `pi_adguard_ip` (Ansible)

Set in the same defaults file. Must equal the LAN IP of the host running AdGuard with `hostNetwork=true`, which is pinned by [`k8s/apps/adguard/deployment.yaml`](../../k8s/apps/adguard/deployment.yaml) `nodeSelector`. Today: `192.168.8.12` (rasp-pi-03).

The two pins (`pi_tailscale_ip` for routing, `pi_adguard_ip` for DNS) are independent — moving AdGuard to a different host doesn't require moving the subnet router (and vice versa).
