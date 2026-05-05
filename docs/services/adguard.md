# AdGuard Home

> **Status:** Active · **Node:** rasp-pi-03 · **Namespace:** adguard · **Ingress:** <https://adguard.tail57bf10.ts.net>
> **Manifests:** [`k8s/apps/adguard/`](../../k8s/apps/adguard/) · **Last reviewed:** 2026-04-23

DNS server with ad-blocking + filtering for the home LAN. Runs with `hostNetwork` on rasp-pi-03 so it can listen on port 53 directly.

## Overview

AdGuard Home is the DNS resolver for the entire home network (192.168.8.0/24 and 192.168.9.0/24). It blocks ads/trackers via blocklists and provides per-client filtering rules. The web UI is exposed only on the tailnet.

## Architecture

- **Pod placement:** pinned to `rasp-pi-03` via `nodeSelector` (DNS needs to be reachable on the LAN, and this Pi has a stable LAN IP)
- **Networking:** `hostNetwork: true` so port 53 binds to the node's LAN IP
- **Storage:** PV at `/mnt/ssd/k3s-storage/adguard` for config + filter lists
- **Web UI:** standard Tailscale ingress at `adguard.tail57bf10.ts.net`

## Security

Pod runs as `nobody:nogroup` (UID/GID 65534):

- `runAsUser: 65534`, `runAsGroup: 65534`, `fsGroup: 65534`
- Drops all capabilities except `NET_BIND_SERVICE` (port 53), `SETUID`, `SETGID` (init-time user switching)
- All other capabilities dropped — least privilege

## Configuration

- LAN router (Opal OpenWrt) hands out `192.168.8.X` (the rasp-pi-03 LAN IP) as DNS server via DHCP
- AdGuard upstreams to Cloudflare DoH (`https://1.1.1.1/dns-query`) by default; configurable in the UI

## Operations

### One-time PV setup (Pi-side)

```bash
ssh rasp-pi-03
sudo chown -R 65534:65534 /mnt/ssd/k3s-storage/adguard
sudo chmod -R u+rwX,g+rX,o-rwx /mnt/ssd/k3s-storage/adguard
```

Without this, the pod CrashLoopBackOffs with `operation not permitted` on the volume mount.

### Restart

```bash
kubectl rollout restart deployment adguard -n adguard
```

### Access the UI

```text
https://adguard.tail57bf10.ts.net
```
(only reachable from the tailnet)

## Troubleshooting

### CrashLoopBackOff with `operation not permitted`
Volume ownership is wrong. Run the chown above.

### Hosts on the LAN can't resolve DNS
Check the pod is running and listening:
```bash
kubectl get pods -n adguard -o wide
ssh rasp-pi-03 -- ss -tlnp | grep :53
```
If empty, the pod didn't get `hostNetwork` privileges or the node has port 53 already bound.

### Filter lists not updating

## Upstream DNS — Mullvad family (manual config)

AdGuard's filter lists are excellent but the upstream resolver matters for
defense-in-depth: anything AdGuard's lists miss should still be blocked
upstream. Pair AdGuard's blocklists with **Mullvad family DNS** as upstream:

1. Open `https://adguard.tail57bf10.ts.net` → **Settings → DNS settings**.
2. Replace **Upstream DNS servers** with:

   ```text
   tls://family.dns.mullvad.net
   tls://1dot1dot1dot1.cloudflare-dns.com
   https://dns.quad9.net/dns-query
   ```

   (Use `tls://all.dns.mullvad.net` instead of `family` if you also want
   social-media domains blocked. `family` covers ads, trackers, malware,
   adult, and gambling — but keeps Twitter / Instagram reachable.)
3. **Bootstrap DNS servers**: `1.1.1.1, 9.9.9.9`
4. **Save** and **Apply**.

Why: when the Pi is up, clients hit AdGuard first (rich blocklists, per-client
rules, query log). AdGuard then resolves anything-not-blocked via Mullvad
family DNS, which still drops gambling/adult/malware. When the Pi crashes,
the Opal failover script (cron, every minute) reconfigures dnsmasq to use
the same Mullvad family IPs (`194.242.2.6` / `2a07:e340::6`) directly, so
clients keep filtered DNS even during AdGuard outage.

Quick visibility: `make dns-status` from the dev machine shows current
upstream + a sample query against a gambling sentinel domain.

## Related

- **Networking model:** [`../architecture/networking.md`](../architecture/networking.md)
- **All app ingress hostnames:** [`../reference/tailnet-services.md`](../reference/tailnet-services.md)
