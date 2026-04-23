# Torrent P2P Debugging

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

When the VPN is up (`***` shows a *** public IP) but torrents still won't connect to peers. This is a different problem from a VPN failure — for that, see [`../runbooks/***-vpn-failure.md`](../runbooks/***-vpn-failure.md).

---

## Sanity Check First

Confirm the symptom matches the right runbook:

```bash
QB_POD=$(kubectl get pod -n media -l app=*** -o jsonpath='{.items[0].metadata.name}')

# 1. VPN actually up?
kubectl exec -n media "$QB_POD" -c *** -- curl -s ifconfig.me
# expect: 193.32.127.XXX

# 2. *** transfer status
kubectl exec -n media "$QB_POD" -c *** -- curl -s \
  -u admin:<password> \
  http://localhost:8080/api/v2/transfer/info | jq .connection_status
# expect: "connected" — if "firewalled" or "disconnected", you're in the right place
```

If `connection_status` is `"firewalled"` or `"disconnected"`, follow the phases below in order — each phase is cheap to check and rules out one hypothesis.

---

## Phase 1 — NetworkPolicy

The most common cause. The `media` namespace has a NetworkPolicy that may block P2P egress.

```bash
kubectl describe networkpolicy -n media
```

Look for the egress rules. P2P needs:

| Port / Proto | Direction | Why |
|---|---|---|
| 80 / 443 TCP | egress | tracker HTTP/HTTPS announces |
| 6881 TCP / UDP | egress | BitTorrent peer connections (***'s listen port) |
| 51820 UDP | egress | WireGuard to *** endpoint |
| 53 UDP/TCP | egress | DNS to kube-system |

If 6881 isn't allowed → P2P traffic dies inside the cluster. Test (TEMPORARILY):
```bash
kubectl delete networkpolicy <name> -n media
sleep 30

# Re-check connection_status — if it flips to "connected", you found it
```

**Fix:** edit the NetworkPolicy to add the missing egress rule, commit, push. Don't leave the policy deleted.

---

## Phase 2 — Tracker Reachability

If NetworkPolicy is fine, confirm trackers are reachable from inside the *** network namespace.

```bash
# DNS
kubectl exec -n media "$QB_POD" -c *** -- nslookup tracker.opentrackr.org
kubectl exec -n media "$QB_POD" -c *** -- cat /etc/resolv.conf

# Reach a tracker
kubectl exec -n media "$QB_POD" -c *** -- \
  curl -s -m 5 -v http://tracker.opentrackr.org:1337/announce 2>&1 \
  | grep -E "(Connected|Trying|Failed|refused)"
```

Common failures:

- **No DNS resolution** — `/etc/resolv.conf` should point to the cluster DNS (10.43.0.10). If it points to ***'s DNS but *** DNS is broken, change `DNS_ADDRESS` in the *** env to `1.1.1.1`.
- **Connection refused** — the tracker is being blocked at the VPN exit (*** blocks some trackers). Try a different exit server.
- **Connection times out** — the tracker is offline (try 2-3 alternates from the same trackerlist).

---

## Phase 3 — Port Binding

***'s listening port (default 6881) must be properly bound. *** **no longer supports port forwarding** (since May 2023), so the port is open inside the pod's netns but the *** server drops inbound — this is fine for outbound, but means you can't accept incoming peer connections.

```bash
# Confirm *** is listening
kubectl exec -n media "$QB_POD" -c *** -- ss -tlnp 2>/dev/null | grep 6881
```

If the listen port isn't 6881, *** picked another (random). Check Tools → Options → Connection → "Port used for incoming connections" in the WebUI.

**Reality check:** since *** killed port forwarding, all peer connections are outbound only. This means:

- Healthy torrents (many seeders) — minimal impact
- Rare torrents (few seeders) — significantly slower
- Private trackers — ratio may suffer

There's nothing to fix here; this is a *** design choice. See [`../services/***.md#***-killed-port-forwarding-may-2023`](../services/***.md#***-killed-port-forwarding-may-2023) for the workarounds.

---

## Phase 4 — DHT / PEX

If trackers are unreachable but DHT works, you can still find peers. Verify DHT is enabled and bootstrapping:

```bash
kubectl exec -n media "$QB_POD" -c *** -- curl -s \
  -u admin:<password> \
  http://localhost:8080/api/v2/transfer/info | jq '{dht_nodes, connection_status}'
```

`dht_nodes` should be > 50 within ~5 min of pod start. If it stays at 0:

- DHT is disabled — Tools → Options → BitTorrent → enable DHT, PEX, LSD
- UDP 6881 is blocked — go back to Phase 1 (NetworkPolicy egress)

---

## Phase 5 — Permissions / Storage

Last resort. If *** can connect to peers but downloads fail with permission errors, check:

```bash
# Owner of /data
kubectl exec -n media "$QB_POD" -c *** -- ls -ld /data /data/torrents

# expect: drwxrwxr-x ... 1000 1000 ...
```

If wrong, fix on the Pi:
```bash
ssh rasp-pi-04
sudo chown -R 1000:1000 /mnt/storage/data
sudo chmod -R u+rwX,g+rwX,o-rwx /mnt/storage/data
```

---

## Triage Decision Tree

```text
connection_status = "connected" + DHT > 50 + downloads work?
  → not a connectivity issue (check tracker health, indexer config)

connection_status = "firewalled"?
  → Phase 1 (NetworkPolicy) — most common
  → Phase 3 (Port binding) — secondary

connection_status = "disconnected"?
  → Phase 2 (tracker DNS / reachability)
  → Phase 4 (DHT bootstrap)

VPN actually broken (no public IP from ***)?
  → ../runbooks/***-vpn-failure.md  (wrong document)
```

## Related

- **VPN failure runbook:** [`../runbooks/***-vpn-failure.md`](../runbooks/***-vpn-failure.md)
- ***** architecture:** [`../services/***.md`](../services/***.md)
- **NetworkPolicies design:** [`../security/network-policies.md`](../security/network-policies.md)
- **Last security review:** [`../reviews/2026-01-28-***-security.md`](../reviews/2026-01-28-***-security.md)
