# AdGuard Home Deployment

## Overview
AdGuard Home DNS server running on `rasp-pi-04` with hostNetwork for LAN-wide DNS filtering.

## Security Context

### Pod-level SecurityContext
- **runAsUser: 65534** - Run as `nobody` user
- **runAsGroup: 65534** - Run as `nogroup` group  
- **fsGroup: 65534** - Ensure volume ownership matches

### Container Capabilities
Required capabilities for DNS service:
- **NET_BIND_SERVICE** - Bind to privileged port 53
- **SETUID/SETGID** - User switching during initialization

All other capabilities are dropped (principle of least privilege).

## Prerequisites

### Storage Initialization (Required!)
The PersistentVolume path must be owned by `nobody:nogroup` (UID:GID 65534:65534):

```bash
# On rasp-pi-04 host:
sudo chown -R 65534:65534 /mnt/ssd/k3s-storage/adguard
sudo chmod -R u+rwX,g+rX,o-rwx /mnt/ssd/k3s-storage/adguard
```

## Troubleshooting

### Pod in CrashLoopBackOff with "operation not permitted"
**Root Cause**: Missing capabilities or incorrect file ownership

**Fix**:
1. Verify security context includes `NET_BIND_SERVICE`, `SETUID`, `SETGID` capabilities
2. Check PV ownership is 65534:65534
3. Re-run ownership fix command above
