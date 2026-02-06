# Media Stack Security Assessment & Implementation

**Date:** 2026-01-30
**Status:** ⚠️ VPN ROUTING ISSUES - *** REVERTED TO FUNCTIONAL STATE

**UPDATE:** *** VPN sidecar has been reverted due to VPN routing issues preventing indexer access. Service is now functional without VPN.

## 📋 Executive Summary

### Security Improvements Implemented
1. ✅ Network policy created for media namespace isolation
2. ❌ *** VPN sidecar attempted for *** (reverted due to routing issues)
3. ✅ *** has VPN protection (existing - but routing broken)
4. ✅ ***/*** configured for internal-only traffic
5. ⚠️ **CRITICAL ISSUE:** VPN tunnel establishes but routing is not working

---

## 🔒 Current Security Status

### Protected Services (VPN-Enabled)
| Service | VPN Status | DNS | Public IP | Risk Level |
|---------|-----------|-----|-----------|-----------|
| *** | ⚠️ Configured but not routing | Cloudflare (1.1.1.1) | Exposing ISP IP | **CRITICAL** |

### Unprotected Services (Direct Internet Access)
| Service | VPN Status | Purpose | Risk Level |
|---------|-----------|---------|-----------|
| *** | ❌ No VPN (reverted) | Indexer searches - **IP EXPOSED** | **HIGH** |
| *** | ❌ No VPN | Internal communication with ***/*** | **LOW** |
| *** | ❌ No VPN | Internal communication with ***/*** | **LOW** |
| *** | ❌ No VPN | Cloudflare solver for *** | **MEDIUM** |

---

## 🚨 Current Critical Issue

### VPN Tunnel Not Routing Traffic

**Problem:**
- WireGuard tunnel establishes successfully (tun0 interface up)
- Tunnel has IP address: 10.67.24.36/32
- **BUT:** Default route still points to eth0 (10.42.7.1) instead of tun0
- Result: All traffic bypasses VPN and uses ISP connection

**Evidence:**
```bash
# Tunnel is UP
6: tun0: <POINTOPOINT,MULTICAST,NOARP,UP,LOWER_UP> mtu 1320
    inet 10.67.24.36/32 scope global tun0

# But routing is WRONG
default via 10.42.7.1 dev eth0  # ← Should be via tun0!
10.42.0.0/16 via 10.42.7.1 dev eth0
```

***** Logs Show:**
```
ERROR [ip getter] Get "https://ipinfo.io/": context deadline exceeded
INFO [healthcheck] program has been unhealthy: restarting VPN
```

**Root Cause (Suspected):**
1. *** account may have connection limits
2. Multiple pod restarts may have triggered rate limiting
3. *** routing configuration issue in Kubernetes network namespace
4. *** server (193.32.127.66) may be blocking connections

---

## 🎯 What We Tried

### Attempts to Fix VPN Routing

1. **Changed DNS to *** (193.36.144.130)** → VPN stopped working
2. **Reverted to Cloudflare DNS (1.1.1.1)** → Still not working
3. **Removed DNS override entirely** → Still not working
4. **Scaled down *** (single VPN connection)** → Still not working
5. **Deleted and recreated pods** → Still not working
6. **Reverted to exact original configuration** → Still not working

### Architecture Decisions Made

**Decision 1: Priority Services Only**
- ✅ VPN for *** (P2P torrenting - highest risk)
- ✅ VPN for *** (public indexer queries - high risk)
- ❌ No VPN for ***/*** (internal traffic only - low risk)

**Rationale:** *** limits simultaneous connections per account. Using 4 VPN sidecars caused connection conflicts.

**Decision 2: Network Policy for Defense-in-Depth**
- Created Kubernetes NetworkPolicy for media namespace
- Restricts ingress/egress to only necessary traffic
- Allows internal pod-to-pod communication
- Permits Tailscale access for WebUI
- Blocks all other external traffic by default

---

## 📐 Network Architecture

### Current Traffic Flow

```
┌─────────────────────────────────────────────────────────────┐
│                      Media Namespace                         │
│                                                              │
│  ┌──────────────┐                                           │
│  │  *** │──┐                                        │
│  │  + ***   │  │  ⚠️ VPN configured but not routing   │
│  └──────────────┘  │                                        │
│                     ├──→ *** VPN (193.32.127.66)        │
│  ┌──────────────┐  │     └─→ Should show Swiss IP          │
│  │   ***   │──┘         ⚠️ Currently: No connectivity │
│  │  + ***   │                                           │
│  └──────────────┘                                           │
│                                                              │
│  ┌──────────────┐      ┌──────────────┐                    │
│  │    ***    │◄────►│    ***    │                    │
│  │   (No VPN)   │      │   (No VPN)   │                    │
│  └──────────────┘      └──────────────┘                    │
│         │                      │                             │
│         └──────────┬───────────┘                             │
│                    ▼                                         │
│            Internal Network                                  │
│         (10.42.0.0/16 - K8s Pods)                           │
│         (10.43.0.0/16 - K8s Services)                       │
│         (100.64.0.0/10 - Tailscale)                         │
└─────────────────────────────────────────────────────────────┘
```

### Network Policy Rules

**Ingress (Incoming):**
- ✅ Allow from same namespace (media)
- ✅ Allow from kube-system (metrics/health checks)
- ✅ Allow from tailscale namespace (WebUI access on ports 8080, 7878, 8989, 9696, 8191)
- ❌ Deny all other ingress

**Egress (Outgoing):**
- ✅ Allow to same namespace (media)
- ✅ Allow to kube-system on port 53 (DNS)
- ✅ Allow to VPN endpoint (193.32.127.66:51820)
- ✅ Allow HTTP/HTTPS (ports 80, 443)
- ✅ Allow *** control port (8000)
- ❌ Deny all other egress by default

---

## 🛠️ Files Modified

```
k8s/apps/***/deployment.yaml (reverted to original)
k8s/apps/***/deployment.yaml (+ *** sidecar)
k8s/apps/***/deployment.yaml (no changes - no VPN)
k8s/apps/***/deployment.yaml (no changes - no VPN)
k8s/apps/***/network-policy.yaml (new)
```

---

## 🔧 Next Steps to Fix VPN

### Option 1: Investigate *** Account (Recommended)
1. Check *** account dashboard for active connections
2. Verify WireGuard key hasn't expired
3. Check if account has connection limits enabled
4. Try generating a new WireGuard key
5. Test connection from a different location to rule out IP blocking

### Option 2: Debug *** Routing
1. Check *** GitHub issues for similar routing problems
2. Try setting `FIREWALL_DEBUG=on` to get more detailed logs
3. Verify iptables rules are being applied correctly
4. Test with different *** versions (currently v3.38.0)

### Option 3: Alternative VPN Architecture
1. **Shared VPN Gateway:** Deploy single *** pod, route all services through it
2. **Host-level VPN:** Configure VPN on the Kubernetes node itself
3. **SOCKS5 Proxy:** Use *** SOCKS5 proxy instead of VPN tunnel

### Option 4: Verify Cluster Networking
1. Check if CNI (Calico/Flannel) has issues with TUN devices
2. Verify `/dev/net/tun` is accessible from pods
3. Check for conflicting network policies
4. Test VPN on a different Kubernetes node

---

## 📊 Security Scorecard

| Category | Before | After | Status |
|----------|--------|-------|--------|
| Torrent Traffic Encryption | ✅ | ✅ | Maintained |
| Torrent IP Protection | ✅ | ⚠️ | **At Risk** (VPN not routing) |
| Indexer Query Privacy | ❌ | ⚠️ | Configured but not active |
| DNS Privacy | ❌ | ⚠️ | Configured but not active |
| Kill Switch Protection | ✅ | ✅ | Active (firewall enabled) |
| Network Isolation | ❌ | ✅ | **Improved** (NetworkPolicy) |

**Overall Grade:** C+ (Was B, downgraded due to VPN routing issue)

---

## 🎓 Lessons Learned

1. ***** Connection Limits:** Can't use same WireGuard key for 4+ simultaneous connections
2. ***** in Kubernetes:** Routing can be tricky in shared network namespaces
3. **Network Policy Value:** Provides defense-in-depth even when VPN fails
4. **Architecture Matters:** Internal-only services (***/***) don't need VPN
5. **DNS Configuration:** *** DNS (193.36.144.130) may not always work - Cloudflare (1.1.1.1) more reliable

---

## 📝 Recommended Security Posture

### Immediate (Fix VPN)
1. **Investigate *** account status**
2. **Generate new WireGuard keys if needed**
3. **Test VPN connectivity manually before deploying**

### Short-term (Harden Infrastructure)
1. **Enable SOPS secret encryption** (PR #106 ready to merge)
2. **Implement Pod Security Standards** (restrict privileged containers)
3. **Add egress network policies** for tighter control
4. **Deploy cluster-wide DNS resolver** with encrypted upstream

### Long-term (Best Practices)
1. **Implement cert-manager** for automatic TLS certificates
2. **Deploy Falco** for runtime security monitoring
3. **Add OPA/Gatekeeper** for policy enforcement
4. **Implement Vault** for dynamic secret management
5. **Set up audit logging** for compliance

---

## 🆘 Debugging Commands

```bash
# Check VPN tunnel status
kubectl exec -n media -c *** POD_NAME -- ip addr show tun0

# Check routing table
kubectl exec -n media -c *** POD_NAME -- ip route show

# Test VPN connectivity
kubectl exec -n media -c *** POD_NAME -- curl -m 10 http://127.0.0.1:8000/v1/publicip/ip

# Check *** logs
kubectl logs -n media -l app=*** -c *** --tail=50

# Verify network policy
kubectl describe networkpolicy media-network-policy -n media

# Check firewall rules
kubectl exec -n media -c *** POD_NAME -- iptables -L -n
```

---

## 📚 References

- [*** Wiki](https://github.com/qdm12/***-wiki)
- [*** WireGuard Setup](https://***.net/en/help/wireguard-and-***-vpn)
- [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [*** Anonymous Mode](https://github.com/***/***/wiki/Anonymous-Mode)

---

**Conclusion:** Security improvements were implemented but VPN routing needs urgent attention. The network policy provides some protection, but VPN is critical for torrent traffic privacy.
