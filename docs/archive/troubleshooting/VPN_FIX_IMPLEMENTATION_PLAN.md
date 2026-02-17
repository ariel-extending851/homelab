---
DEPRECATED: This document is archived for historical purposes. The core issue has been resolved in the latest *** deployment manifest.
---

# 🔧 VPN Fix Implementation Plan

**Date:** 2026-01-30
**Issue:** *** VPN routing broken - torrents cannot download
**Solution:** Fix IPv6 routing + Regenerate *** WireGuard key
**Estimated Time:** 20 minutes
**Risk Level:** LOW (easily reversible)

---

## 🎯 Objective

Fix *** VPN connectivity so torrents can download. Currently:
- ❌ VPN tunnel fails to establish (IPv6 routing error)
- ❌ Kill switch blocks all traffic (no internet access)
- ❌ Torrents show 0 seeds/0 peers (cannot connect)

---

## 📋 Prerequisites

### Required Access:
- [ ] *** account login credentials (https://***.net/en/account/)
- [ ] kubectl access to homelab cluster
- [ ] Git access to modify deployment files

### Current State Backup:
```bash
# Backup current secret (in case we need to rollback)
kubectl get secret ***-secret -n media -o yaml > ~/***-secret-backup.yaml

# Backup current deployment
cp k8s/apps/***/deployment.yaml k8s/apps/***/deployment.yaml.backup
```

---

## 🚀 Implementation Steps

### STEP 1: Regenerate *** WireGuard Key (5 minutes)

#### 1.1 Login to *** Account
1. Open browser: https://***.net/en/account/
2. Enter your account number (16 digits)
3. Click "Log in"

#### 1.2 Access WireGuard Configuration
1. Click "WireGuard configuration" in left menu
2. You should see your current keys listed

#### 1.3 Delete Old Key
1. Find the key associated with your homelab (might be named "homelab" or similar)
2. Click the **trash icon** next to it
3. Confirm deletion

#### 1.4 Generate New Key
1. Click "**Generate new key pair**"
2. Optional: Give it a name like "homelab-k3s"
3. Click "Generate"
4. You'll see the new key displayed

#### 1.5 Copy New Credentials
**IMPORTANT:** Keep this browser tab open! You need to copy these values:

1. **Private Key** - Long base64 string (e.g., `cG9pbnRsZXNzIGV4YW1wbGUK...`)
2. **IP Address** - IPv4 address (e.g., `10.67.24.36/32`)

**Example output you'll see:**
```
Private key: cG9pbnRsZXNzIGV4YW1wbGUK... (44 characters)
IP address: 10.67.24.36/32
```

**Copy both values to a notepad - you'll need them in Step 2!**

---

### STEP 2: Update Kubernetes Secret (5 minutes)

#### 2.1 Encode Values to Base64
Open terminal and run:

```bash
# Encode private key (replace with YOUR private key from ***)
echo -n 'YOUR_PRIVATE_KEY_HERE' | base64

# Encode IP address (replace with YOUR IP from ***)
echo -n 'YOUR_IP_ADDRESS_HERE' | base64
```

**Example:**
```bash
# If your private key is: cG9pbnRsZXNzIGV4YW1wbGUK
echo -n 'cG9pbnRsZXNzIGV4YW1wbGUK' | base64
# Output: Y0c5cGJuUnNaWE56SUdWNFlXMXdiR1VL

# If your IP is: 10.67.24.36/32
echo -n '10.67.24.36/32' | base64
# Output: MTAuNjcuMjQuMzYvMzI=
```

**Save these base64 values - you need them next!**

#### 2.2 Edit Kubernetes Secret
```bash
kubectl edit secret ***-secret -n media
```

This opens the secret in your default editor (vi/nano).

#### 2.3 Update Secret Values
Find and replace these two lines:

```yaml
apiVersion: v1
data:
  WIREGUARD_ADDRESSES: <OLD_BASE64_VALUE>  # ← Replace this
  WIREGUARD_PRIVATE_KEY: <OLD_BASE64_VALUE>  # ← Replace this
kind: Secret
metadata:
  name: ***-secret
  namespace: media
type: Opaque
```

**Replace with YOUR base64-encoded values from Step 2.1:**

```yaml
data:
  WIREGUARD_ADDRESSES: MTAuNjcuMjQuMzYvMzI=  # ← Your encoded IP
  WIREGUARD_PRIVATE_KEY: Y0c5cGJuUnNaWE56SUdWNFlXMXdiR1VL  # ← Your encoded key
```

**Save and exit:**
- If using vi: Press `ESC`, type `:wq`, press `ENTER`
- If using nano: Press `CTRL+X`, press `Y`, press `ENTER`

#### 2.4 Verify Secret Updated
```bash
kubectl get secret ***-secret -n media -o yaml | grep -E "(WIREGUARD_ADDRESSES|WIREGUARD_PRIVATE_KEY)"
```

You should see your new base64 values.

---

### STEP 3: Fix IPv6 Routing in Deployment (2 minutes)

#### 3.1 Edit Deployment File
Open the file:
```bash
cd ~/homelab  # Or wherever your homelab repo is
nano k8s/apps/***/deployment.yaml
```

#### 3.2 Add IPv4-Only Routing
Find this section (around line 76):
```yaml
            # Explicitly disable IPv6 to prevent IPv6 endpoint selection
            - name: VPN_IPV6
              value: "off"
            # Private key and addresses from secret
```

**Add ONE new line after `VPN_IPV6`:**
```yaml
            # Explicitly disable IPv6 to prevent IPv6 endpoint selection
            - name: VPN_IPV6
              value: "off"
            # Force IPv4-only routing to avoid IPv6 conflicts
            - name: WIREGUARD_ALLOWED_IPS
              value: "0.0.0.0/0"
            # Private key and addresses from secret
```

**Exact code to add (copy-paste):**
```yaml
            # Force IPv4-only routing to avoid IPv6 conflicts
            - name: WIREGUARD_ALLOWED_IPS
              value: "0.0.0.0/0"
```

#### 3.3 Save and Verify
```bash
# Save the file (CTRL+X, Y, ENTER in nano)

# Verify the change
grep -A2 "VPN_IPV6" k8s/apps/***/deployment.yaml
```

**Expected output:**
```yaml
            - name: VPN_IPV6
              value: "off"
            # Force IPv4-only routing to avoid IPv6 conflicts
            - name: WIREGUARD_ALLOWED_IPS
              value: "0.0.0.0/0"
```

---

### STEP 4: Apply Changes (3 minutes)

#### 4.1 Apply Deployment Update
```bash
kubectl apply -f k8s/apps/***/deployment.yaml
```

**Expected output:**
```
deployment.apps/*** configured
```

#### 4.2 Watch Pod Restart
```bash
kubectl get pods -n media -l app=*** -w
```

You'll see:
1. Old pod terminating
2. New pod creating
3. New pod starting (0/2 → 2/2)

**Press CTRL+C when you see:**
```
***-xxxxx-yyyyy   2/2     Running   0          30s
```

#### 4.3 Wait for VPN to Connect
```bash
# Wait 30 seconds for VPN to establish
sleep 30
```

---

### STEP 5: Verify VPN is Working (5 minutes)

#### 5.1 Get Pod Name
```bash
export QB_POD=$(kubectl get pod -n media -l app=*** -o jsonpath='{.items[0].metadata.name}')
echo "Pod name: $QB_POD"
```

#### 5.2 Check *** Logs
```bash
kubectl logs -n media $QB_POD -c *** --tail=30
```

**✅ GOOD - Look for:**
```
INFO [wireguard] Wireguard setup is complete
INFO [ip getter] Public IP address is 193.32.127.XXX (Switzerland, Zurich)
```

**❌ BAD - If you see:**
```
ERROR [vpn] adding IPv6 rule: file exists
ERROR [ip getter] context deadline exceeded
```

#### 5.3 Test VPN Public IP
```bash
kubectl exec -n media $QB_POD -c *** -- \
  curl -s -m 10 http://127.0.0.1:8000/v1/publicip/ip
```

**✅ SUCCESS - Should return:**
```json
{
  "public_ip": "193.32.127.XXX",
  "country": "Switzerland",
  "city": "Zürich",
  "location": "47.3667,8.5500"
}
```

**❌ FAILURE - If you see:**
```json
{"public_ip":""}
```
Or timeout/error → Go to STEP 7 (Troubleshooting)

#### 5.4 Test Routing Table
```bash
kubectl exec -n media $QB_POD -c *** -- ip route show
```

**✅ GOOD - Should show:**
```
default dev tun0 scope link      ← VPN tunnel!
10.42.0.0/16 via 10.42.7.1 dev eth0
```

**❌ BAD - If you see:**
```
default via 10.42.7.1 dev eth0   ← No VPN tunnel!
```

#### 5.5 Test Internet Connectivity
```bash
kubectl exec -n media $QB_POD -c *** -- \
  curl -s -m 10 -o /dev/null -w "%{http_code}" https://google.com
```

**✅ SUCCESS - Should return:** `200`
**❌ FAILURE - If returns:** `000` or timeout

---

### STEP 6: Test Torrent Downloads (5 minutes)

#### 6.1 Open *** WebUI
Open browser: https://***.tail57bf10.ts.net/

Login:
- Username: `admin`
- Password: `7Ct855thBIfuOmz6TvzC0SzOVJ0YVnar`

#### 6.2 Resume One Torrent
1. Select ONE torrent from the list (e.g., row #14 - "[F] Downloading")
2. Right-click → **Start** (or click Resume button)
3. Watch the status column

**✅ SUCCESS - After 10-30 seconds:**
```
Status: Downloading
Seeds: 5 (12)      ← Connected to peers!
Down Speed: 2.5 MB/s  ← Downloading!
```

**❌ FAILURE - Still shows:**
```
Status: Downloading
Seeds: 0 (0)       ← No peers
Down Speed: 0 B/s  ← No download
```

#### 6.3 Check Connection Status
In *** WebUI:
1. Click **Tools** → **Options** → **Connection**
2. Look at bottom: "**Connection status**"

**✅ GOOD:**
```
Status: Connectable
```

**❌ BAD:**
```
Status: Not connectable
```

#### 6.4 Monitor for 2 Minutes
Let the torrent run for 2 minutes. Check if:
- [ ] Seeds/peers increase (should go from 0 to >0)
- [ ] Download speed appears (should be >0 B/s)
- [ ] Progress increases (should see percentage going up)

---

## ✅ Success Criteria

**VPN is working correctly when ALL of these are true:**

| Check | Command | Expected Result |
|-------|---------|----------------|
| ✅ VPN Connected | `kubectl logs -n media $QB_POD -c *** --tail=10` | "Public IP address is 193.32.127.XXX" |
| ✅ Swiss IP | `curl -s http://127.0.0.1:8000/v1/publicip/ip` | `"country":"Switzerland"` |
| ✅ Routing via VPN | `ip route show` | `default dev tun0` |
| ✅ Torrents Connect | *** WebUI | Seeds > 0, Peers > 0 |
| ✅ Download Active | *** WebUI | Down Speed > 0 B/s |

---

## 🔧 STEP 7: Troubleshooting (If Things Don't Work)

### Issue 1: VPN Still Not Connecting

**Symptom:** Still seeing `ERROR [vpn] adding IPv6 rule`

**Fix:**
```bash
# Delete pod to force clean restart
kubectl delete pod -n media $QB_POD

# Wait for new pod
kubectl wait --for=condition=ready pod -l app=*** -n media --timeout=180s

# Re-run verification (Step 5)
```

### Issue 2: Wrong *** Credentials

**Symptom:** `ERROR [wireguard] handshake timeout` or `authentication failed`

**Fix:**
1. Double-check you copied the RIGHT key from *** dashboard
2. Verify base64 encoding has no extra spaces/newlines
3. Re-run Step 2 with correct values

### Issue 3: Kill Switch Blocking Traffic

**Symptom:** VPN connects but still no internet

**Fix:**
```bash
# Check firewall rules
kubectl exec -n media $QB_POD -c *** -- iptables -L -n | grep -E "(DROP|REJECT)"

# If too restrictive, temporarily disable kill switch for testing:
kubectl set env deployment/*** -n media -c *** FIREWALL=off

# Test again, then re-enable:
kubectl set env deployment/*** -n media -c *** FIREWALL=on
```

### Issue 4: Port Not Open

**Symptom:** VPN works, torrents connect, but slow speeds

**Fix:**
Check if port 6881 is open through VPN:
```bash
# In *** WebUI: Tools → Options → Connection
# Note the "Listening Port" (should be 6881)

# Test if port is reachable from internet
# Use online tool: https://www.yougetsignal.com/tools/open-ports/
# Enter *** IP (193.32.127.XXX) and port 6881
```

If not open:
- *** doesn't support port forwarding on all servers
- Consider enabling UPnP in *** (less secure)
- Or use a different VPN provider with port forwarding

---

## 🔄 Rollback Plan (If Everything Fails)

### Option A: Restore Previous Secret
```bash
kubectl apply -f ~/***-secret-backup.yaml
kubectl rollout restart deployment/*** -n media
```

### Option B: Revert Deployment Changes
```bash
git checkout k8s/apps/***/deployment.yaml
kubectl apply -f k8s/apps/***/deployment.yaml
```

### Option C: Disable Kill Switch Temporarily
```bash
kubectl set env deployment/*** -n media -c *** FIREWALL=off
```

**This allows downloads to work (but exposes your IP - not recommended long-term)**

---

## 📊 Expected Timeline

| Step | Duration | Cumulative |
|------|----------|-----------|
| Regenerate *** key | 5 min | 5 min |
| Update K8s secret | 5 min | 10 min |
| Fix deployment YAML | 2 min | 12 min |
| Apply changes | 3 min | 15 min |
| Verify VPN working | 5 min | 20 min |
| Test torrent downloads | 5 min | 25 min |

**Total:** ~25 minutes (including verification)

---

## 📝 Post-Implementation

### Commit Changes
```bash
cd ~/homelab
git add k8s/apps/***/deployment.yaml
git commit -m "fix(vpn): resolve IPv6 routing conflicts in ***

- Add WIREGUARD_ALLOWED_IPS to force IPv4-only routing
- Fixes 'file exists' error on IPv6 rule table 51820
- Enables *** torrent downloads via VPN
- Updated *** WireGuard key (regenerated)

Closes: VPN routing issue blocking torrent connectivity
Tested: *** shows Swiss IP (193.32.127.XXX)
Result: Torrents now connecting to peers successfully"

git push
```

### Update Documentation
```bash
# Update security assessment
nano docs/SECURITY_ASSESSMENT.md

# Change status from:
# "⚠️ VPN ROUTING ISSUES"
# To:
# "✅ VPN WORKING - IPv6 routing fixed"
```

### Monitor Stability
```bash
# Check VPN stays connected over 24 hours
watch -n 300 'kubectl exec -n media $(kubectl get pod -n media -l app=*** -o jsonpath="{.items[0].metadata.name}") -c *** -- curl -s http://127.0.0.1:8000/v1/publicip/ip | jq -r .public_ip'

# Should consistently show: 193.32.127.XXX (not empty)
```

---

## ✅ Completion Checklist

Before marking as complete, verify:

- [ ] *** WireGuard key regenerated
- [ ] Kubernetes secret updated with new credentials
- [ ] `WIREGUARD_ALLOWED_IPS` added to deployment
- [ ] Deployment applied successfully
- [ ] VPN shows Swiss public IP (193.32.127.XXX)
- [ ] Routing table shows `default dev tun0`
- [ ] *** torrents connect to peers (seeds > 0)
- [ ] Download speeds active (speed > 0 B/s)
- [ ] Changes committed to git
- [ ] Documentation updated

---

## 🆘 Get Help

If stuck after following all steps:

1. **Check *** Wiki:** https://github.com/qdm12/***-wiki/blob/main/faq/healthcheck.md
2. **Check *** Status:** https://***.net/en/check
3. **Gather Debug Info:**
   ```bash
   kubectl logs -n media $QB_POD -c *** --tail=100 > ~/***-debug.log
   kubectl exec -n media $QB_POD -c *** -- ip route show > ~/***-routes.log
   kubectl exec -n media $QB_POD -c *** -- iptables -L -n > ~/***-firewall.log
   ```
4. **Share logs** for troubleshooting

---

**Good luck! The fix should work - you've got this! 🚀**
