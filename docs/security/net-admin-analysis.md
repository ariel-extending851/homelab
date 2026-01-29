# Security Analysis: *** NET_ADMIN Capability

## Question
Does the *** VPN sidecar **strictly require** the `NET_ADMIN` capability, or can it be removed/reduced?

## Answer: **STRICTLY REQUIRED**

The `NET_ADMIN` capability is **non-negotiable** for ***'s VPN tunnel functionality.

## Why NET_ADMIN is Required

### 1. TUN/TAP Interface Creation
```bash
# *** must create the tun0 virtual network interface
ip tuntap add dev tun0 mode tun
```
**Required Operations:**
- `TUNSETIFF` ioctl (create TUN device)
- Interface configuration
- MTU settings

### 2. Routing Table Manipulation
```bash
# *** modifies routing to force all traffic through VPN
ip route add default via <vpn-gateway> dev tun0
ip route add <local-subnets> via <pod-gateway> dev eth0
```
**Required Operations:**
- Add/delete routes (`RTM_NEWROUTE`, `RTM_DELROUTE`)
- Modify default gateway
- Policy-based routing

### 3. iptables Firewall (Killswitch)
```bash
# *** configures iptables to block non-VPN traffic
iptables -A OUTPUT -o tun0 -j ACCEPT
iptables -A OUTPUT ! -o lo -j DROP
```
**Required Operations:**
- Create/modify iptables chains
- Set firewall rules
- NAT/MASQUERADE configuration

## Security Mitigations in Place

### ✅ Principle of Least Privilege
```yaml
securityContext:
  capabilities:
    add: ["NET_ADMIN"]     # Only network admin, not all caps
  runAsUser: 0             # Root required for iptables
  allowPrivilegeEscalation: false  # Prevents further escalation
```

### ✅ Container Isolation
- **Network Namespace Sharing:** *** shares ***'s netns but does NOT have NET_ADMIN
- **Filesystem Isolation:** *** has no access to application data
- **Read-Only Root:** (Not currently enforced - potential hardening)

### ✅ Resource Limits
```yaml
resources:
  limits:
    cpu: 100m
    memory: 128Mi
```
Prevents runaway processes even if compromised.

## Alternative Approaches (NOT Viable)

### ❌ Userspace WireGuard (wireguard-go)
**Status:** Already using `WIREGUARD_IMPLEMENTATION=userspace`
**Problem:** Still requires NET_ADMIN for routing and iptables

### ❌ CAP_NET_RAW Only
**Problem:** Cannot create TUN devices or modify routes

### ❌ External VPN Setup (Node-Level)
**Problem:** Breaks pod-level killswitch and Kubernetes network policy

## Verification Commands

### Check Current Capabilities
```bash
kubectl exec -n media deploy/*** -c *** -- \
  cat /proc/1/status | grep Cap
```

### Test Without NET_ADMIN (Expected to Fail)
```bash
# Remove capability and observe failure
kubectl patch deploy *** -n media --type=json \
  -p='[{"op": "remove", "path": "/spec/template/spec/containers/0/securityContext/capabilities"}]'

# Expected error:
# RTNETLINK answers: Operation not permitted
```

## Recommendation

**Keep NET_ADMIN capability** with current mitigations:
- ✅ Scoped to single container (*** only)
- ✅ Least privilege (no other dangerous caps like SYS_ADMIN)
- ✅ Resource-limited
- ✅ No privilege escalation

**Additional Hardening (Optional):**
```yaml
securityContext:
  capabilities:
    add: ["NET_ADMIN"]
    drop: ["ALL"]  # Explicitly drop all other caps
  readOnlyRootFilesystem: true  # Prevent filesystem tampering
  runAsNonRoot: false  # Must be root for iptables
  allowPrivilegeEscalation: false
```

## AWS DevOps Parallel

**Similar to:**
- AWS VPC NAT Gateway (requires privileged networking)
- AWS Transit Gateway (routing between VPCs)
- AWS Network Firewall (packet filtering)

All require elevated network permissions to function.

## References

- [Linux Capabilities Man Page](https://man7.org/linux/man-pages/man7/capabilities.7.html)
- [*** Security Model](https://github.com/qdm12/***/wiki/Setup-guide#security-considerations)
- [Kubernetes Pod Security Standards](https://kubernetes.io/docs/concepts/security/pod-security-standards/)
