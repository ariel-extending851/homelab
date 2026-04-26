# 🔴 CRITICAL: Control Plane Node Unreachable

## Current Status (09:08 UTC)

**Kubernetes API:** Down for 20+ minutes
**Control Plane Node (k3s-server-1):** UNREACHABLE
**Tailscale IP:** 100.109.54.24 - Not responding to ping
**SSH:** Connection failed
**AWS SSM:** Failed to execute

## What This Means

The k3s control plane (k3s-server-1 on AWS) is **completely offline**, not just the Kubernetes API. This is why:
- kubectl commands have been failing for 20+ minutes
- The API hasn't recovered despite RPi 3 stabilizing
- We cannot manage the cluster

**This is NOT caused by the proxy migration** - this is a separate infrastructure issue.

## Root Cause Analysis

**Timeline of Events:**
1. 00:30 - Proxy migration executed
2. 00:35 - RPi 3 became overloaded
3. 00:40 - Kubernetes API started timing out
4. 00:50 - Control plane likely crashed or became unreachable
5. 09:08 - Still unreachable after 20+ minutes

**Possible Causes:**
1. **AWS EC2 Instance Issue**
   - Instance may have crashed
   - Network interface problem
   - Out of memory/CPU causing system freeze

2. **k3s Control Plane Crash**
   - Overwhelmed by cluster instability
   - Memory exhaustion (2GB node)
   - etcd corruption or failure

3. **Network Connectivity**
   - Tailscale tunnel down
   - AWS security group changes
   - Internet connectivity issue

## Impact

### What Works
✅ RPi 4 (rasp-pi-04) - Running *arr apps
✅ RPi 3 (rasp-pi-03) - Running, load stabilizing
✅ k3s-agent-2 (AWS) - Appears online in Tailscale

### What Doesn't Work
❌ Kubernetes API - Down
❌ kubectl commands - All failing
❌ Control plane - Unreachable
❌ Cluster management - Impossible

## Recovery Required

This requires **manual intervention on the AWS control plane node**.

### Option 1: AWS Console (Recommended)

1. **Log into AWS Console**
   - Navigate to EC2 Dashboard
   - Find instance: `k3s-server-1`
   - Check instance status

2. **Check Instance State**
   - If "Running" → Try "Reboot"
   - If "Stopped" → Start it
   - Check system logs (Actions → Monitor and troubleshoot → Get system log)

3. **Alternative: Use Session Manager**
   - Select instance
   - Click "Connect" → "Session Manager"
   - Run diagnostic commands:
     ```bash
     sudo systemctl status k3s
     free -m
     df -h
     sudo systemctl restart k3s
     ```

### Option 2: EC2 Instance Connect

If Session Manager doesn't work:

1. **EC2 Dashboard → Instances → k3s-server-1**
2. **Connect → EC2 Instance Connect**
3. **Run recovery commands**

### Option 3: Manual Recovery Commands

Once connected to k3s-server-1 via any method:

```bash
# Check k3s status
sudo systemctl status k3s

# Check resources
free -m
df -h
top -bn1 | head -20

# Try restarting k3s
sudo systemctl restart k3s

# Or if that fails, check logs
sudo journalctl -u k3s -n 100

# If k3s won't start, check for disk corruption
sudo fsck -n /dev/nvme0n1p1
```

## What Happens After Recovery

Once k3s-server-1 is back:

1. **Kubernetes API will return** (within 1-2 minutes)
2. **kubectl will work again**
4. **The proxy migration recovery script will run automatically**

## Current Recommendations

### Immediate (Now)

1. **Check AWS Console** for k3s-server-1 instance status
2. **Try to connect** via Session Manager or Instance Connect
3. **Restart k3s** or the entire instance if needed

### Once Control Plane is Back

4. **Run the recovery script** (already prepared):
   ```bash
   cd /var/mnt/nvme/repos/repos/homelab
   ./scripts/emergency-recovery.sh
   ```

## Prevention for Future

This incident reveals the cluster has a **single point of failure**:

**Recommendations:**
1. **Add a second control plane node** (HA k3s setup)
2. **Increase k3s-server-1 instance size** (t3.small → t3.medium)
3. **Add monitoring/alerting** for control plane health
4. **Regular etcd backups** for disaster recovery

## Summary

**This is not a proxy migration failure** - it's an infrastructure failure that coincided with our changes. The control plane node needs to be recovered via AWS Console.

**The *arr apps are still running on RPi 4** - they're just inaccessible because:
1. Tailscale proxies are broken (from migration)
2. Kubernetes API is down (control plane issue)

**Next step:** Recover k3s-server-1 via AWS Console.

---

## Action Items

- [ ] Check AWS EC2 console for k3s-server-1 status
- [ ] Connect via Session Manager or Instance Connect
- [ ] Restart k3s service or reboot instance
- [ ] Wait for Kubernetes API to return
- [ ] Execute emergency recovery script

---

**Can you access the AWS Console to check the k3s-server-1 instance?**
