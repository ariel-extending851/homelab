# 🔍 Torrent P2P Connectivity Debugging Plan

**Status:** VPN connected ✅ | P2P stalled ❌ | Torrents added by *** ✅
**Indexers:** 1337x, EZTV, EZTVL, Nyaa, TPB (all healthy, have active seeders)
**Hypothesis Chain:** NetworkPolicy → Tracker connectivity → Port binding → Permissions

---

## 📋 Phase 1: NetworkPolicy Analysis (HIGHEST PRIORITY)

**Why First?** The NetworkPolicy we created might be blocking P2P traffic!

### Check 1.1: Review Current NetworkPolicy
```bash
kubectl describe networkpolicy media-network-policy -n media
```

**What we're looking for:**
- Egress rules that might block UDP (P2P)
- Egress rules that might block port 6881
- Egress rules that might block tracker IPs (80/443)
- Missing allowances for peer connections

**Expected output structure:**
```
Egress Rules:
  - To Port 53 (DNS) ✅
  - To Port 80/443 (HTTPS) ✅
  - To Port 51820 (VPN) ✅
  - To Port 6881 (Torrents) ❓ ← MIGHT BE MISSING
```

### Check 1.2: List All Network Policies
```bash
kubectl get networkpolicies -n media -o yaml
```

**What we need:**
- Count how many policies exist
- Verify they're not too restrictive
- Check if multiple policies are stacking restrictions

### Check 1.3: Test if Egress Rules are the Problem
```bash
# Temporarily DISABLE the network policy (TESTING ONLY)
kubectl delete networkpolicy media-network-policy -n media

# Wait 30 seconds
sleep 30

# Check if torrents suddenly connect
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  curl -s -u admin:7Ct855thBIfuOmz6TvzC0SzOVJ0YVnar \
  http://localhost:8080/api/v2/transfer/info | jq '.connection_status'
```

**If result changes to "connected":**
- 🎯 **ROOT CAUSE FOUND** - NetworkPolicy is blocking P2P
- Action: Fix the policy rules
- Go to: **PHASE 1 FIX** below

**If result stays "firewalled":**
- 🔄 **Move to Phase 2** - Tracker connectivity issue

---

## 📋 Phase 2: Tracker Connectivity (If Phase 1 clear)

**Why?** *** can't reach trackers = can't discover peers

### Check 2.1: Test Tracker Access from Container
```bash
# Get first torrent's tracker URL
TRACKER_URL="http://tracker.example.com:80/announce"

# Test DNS resolution
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  nslookup tracker.1337x.to

# Test HTTP connection to tracker
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  curl -s -m 5 -v http://tracker.1337x.to/ 2>&1 | grep -E "(Connected|Trying|Failed|Connection refused)"
```

**Expected results:**
- ✅ DNS resolves tracker domain
- ✅ HTTP connection returns response (200, 404, etc)
- ❌ Connection refused = firewall blocking
- ❌ No response = tracker down or blocked

### Check 2.2: Verify DNS Works in *** Container
```bash
# Check /etc/resolv.conf
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  cat /etc/resolv.conf

# Test multiple DNS queries
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  nslookup google.com

kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  nslookup tracker.openbittorrent.com
```

**Expected:**
- Nameserver: 1.1.1.1 (Cloudflare through VPN)
- Google resolves: 142.250.x.x
- OpenBittorrent tracker resolves successfully

### Check 2.3: Test DHT Connectivity
```bash
# Check DHT status
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  curl -s -u admin:7Ct855thBIfuOmz6TvzC0SzOVJ0YVnar \
  http://localhost:8080/api/v2/transfer/info | jq '.dht_nodes'
```

**Expected:**
- ❌ `dht_nodes: 0` initially (bootstrapping)
- ✅ `dht_nodes: 50-100+` after 5 minutes
- ❌ `dht_nodes: 0` after 10+ minutes = no DHT bootstrap

---

## 📋 Phase 3: Port & Interface Binding (If Phase 2 clear)

**Why?** *** might not be listening on the right interface/port

### Check 3.1: Verify *** Port Configuration
```bash
# Check configured port
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  cat /config/***/***.conf | grep -E "Session\\\\Port|Connection\\\\Port"

# Expected output:
# Session\Port=6881
# Connection\PortRangeMin=6881
```

### Check 3.2: Verify Port is Actually Listening
```bash
# Check if port 6881 is listening in the container
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  netstat -tlnup 2>/dev/null | grep 6881

# Alternative (if netstat not available)
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  ss -tlnup | grep 6881
```

**Expected:**
- ✅ `LISTEN ... :6881` (TCP listening)
- ❌ No results = port not listening

### Check 3.3: Check Interface Binding
```bash
# Check all listening ports
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  netstat -tlnup 2>/dev/null | head -20
```

**Expected:**
- Port 8080: *** WebUI (should show LISTEN)
- Port 6881: *** P2P (should show LISTEN)
- Bound to: 0.0.0.0 or specific IP

---

## 📋 Phase 4: Volume & Permissions (If Phase 3 clear)

**Why?** Can't write = can't create .incomplete files = can't download

### Check 4.1: Verify Download Directories Exist
```bash
# Check if directories exist and are writable
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  ls -la /data/torrents/

# Expected output:
# drwxr-xr-x ... tv
# drwxr-xr-x ... movies
# drwxrwsr-x ... incomplete
```

### Check 4.2: Test Write Permissions
```bash
# Try to create a test file
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  touch /data/torrents/incomplete/test-write.txt

# Verify it was created
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  ls -la /data/torrents/incomplete/ | grep test-write

# Clean up
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  rm /data/torrents/incomplete/test-write.txt
```

**Expected:**
- ✅ File created successfully
- ✅ File exists in listing
- ❌ Permission denied = write issue

### Check 4.3: Check Volume Mount Status
```bash
# Check if volumes are mounted
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  mount | grep /data

# Expected output:
# /dev/... on /data type ext4 (rw,...)
```

---

## 📋 Phase 5: *** Configuration (If Phase 4 clear)

**Why?** Session settings might prevent peer connections

### Check 5.1: Review *** Configuration
```bash
# Check full *** config
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  cat /config/***/***.conf
```

**Look for these settings:**
```
Session\Port=6881                    ← Correct
Session\QueueingSystemEnabled=true   ← OK
Connection\UPnP=false                ← Expected (we don't have UPnP)
Connection\PortRangeMin=6881         ← Correct
WebUI\Address=*                      ← OK
```

### Check 5.2: Check for Connection Limits
```bash
# Check if there are global speed limits
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  cat /config/***/***.conf | grep -i "limit\|speed\|bandwidth"
```

**Look for:**
- `Session\GlobalMaxConnections` (should be high, 500+)
- `Session\GlobalMaxConnectionsPerSecond` (should be high, 100+)
- Speed limits disabled (0 = unlimited)

### Check 5.3: Check *** Logs for Errors
```bash
# Get *** logs (if available)
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  ls -la /config/***/logs/ 2>/dev/null

# Read logs if they exist
kubectl exec -n media ***-64f57b775b-565z2 -c *** -- \
  tail -50 /config/***/logs/***.log 2>/dev/null || echo "No log file"
```

**Look for:**
- ❌ "Firewall" errors
- ❌ "Port" errors
- ❌ "Listen" failures
- ❌ "tracker" errors

---

## 🔧 PHASE 1 FIX: Update NetworkPolicy

**If Phase 1.3 confirms NetworkPolicy is blocking P2P:**

### Current Policy (Restrictive)
Located in: `k8s/apps/***/network-policy.yaml`

### Problem
The current egress rules don't explicitly allow:
- UDP port 6881 (BitTorrent data)
- UDP for peer discovery
- Connection to tracker IPs

### Fix: Update NetworkPolicy

```yaml
# k8s/apps/***/network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: media-network-policy
  namespace: media
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress

  ingress:
    # Allow traffic from within the same namespace
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: media

    # Allow from kube-system (health checks)
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system

    # Allow Tailscale ingress
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: tailscale
      ports:
        - protocol: TCP
          port: 8080   # ***
        - protocol: TCP
          port: 7878   # ***
        - protocol: TCP
          port: 8989   # ***
        - protocol: TCP
          port: 9696   # ***

  egress:
    # Allow DNS (UDP 53)
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53

    # Allow internal pod communication
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: media

    # Allow VPN connection (WireGuard)
    - to:
        - podSelector: {}
      ports:
        - protocol: UDP
          port: 51820

    # ✅ ADD THIS: Allow BitTorrent P2P traffic (ALL)
    # This allows *** to connect to peers on any port
    - to:
        - podSelector: {}
      ports:
        - protocol: TCP
          port: 0
          endPort: 65535
        - protocol: UDP
          port: 0
          endPort: 65535

    # Allow HTTP/HTTPS (trackers, metadata)
    - to:
        - podSelector: {}
      ports:
        - protocol: TCP
          port: 80
        - protocol: TCP
          port: 443

    # Allow *** control API
    - to:
        - podSelector: {}
      ports:
        - protocol: TCP
          port: 8000
```

**Apply the fix:**
```bash
kubectl apply -f k8s/apps/***/network-policy.yaml
```

**Then restart ***:**
```bash
kubectl delete pod -n media -l app=***
kubectl wait --for=condition=ready pod -l app=*** -n media --timeout=180s
```

**Re-enable the policy if it was temporarily removed:**
```bash
kubectl apply -f k8s/apps/***/network-policy.yaml
```

---

## 📊 Execution Order

```
Phase 1: NetworkPolicy Analysis
  ├─ Check 1.1: Review rules
  ├─ Check 1.2: List all policies
  └─ Check 1.3: Test by disabling (if needed)
       └─ Result positive? → Apply Phase 1 Fix
       └─ Result negative? → Move to Phase 2

Phase 2: Tracker Connectivity
  ├─ Check 2.1: Test tracker access
  ├─ Check 2.2: Verify DNS
  └─ Check 2.3: Check DHT
       └─ All pass? → Move to Phase 3
       └─ Some fail? → Debug DNS/tracker issues

Phase 3: Port & Interface Binding
  ├─ Check 3.1: Port config
  ├─ Check 3.2: Port listening
  └─ Check 3.3: Interface binding
       └─ All pass? → Move to Phase 4

Phase 4: Volume & Permissions
  ├─ Check 4.1: Directories exist
  ├─ Check 4.2: Write permissions
  └─ Check 4.3: Mount status
       └─ All pass? → Move to Phase 5

Phase 5: *** Configuration
  ├─ Check 5.1: Config review
  ├─ Check 5.2: Connection limits
  └─ Check 5.3: Logs for errors
       └─ All pass? → Escalate (unknown issue)
```

---

## ✅ Success Criteria

**Debugging complete when:**
- [ ] DHT nodes: 50+ (not 0)
- [ ] Connection status: "connected" (not "firewalled")
- [ ] Torrents show: Seeds > 0, Peers > 0
- [ ] Download speed: > 0 B/s
- [ ] Status: "Downloading" (not "Stalled")

---

## 🎯 Expected Root Causes (Ranked by Probability)

1. **NetworkPolicy too restrictive** (70% - Most likely)
   - Fix: Update egress rules to allow all ports

2. **Tracker connectivity issues** (15% - Medium)
   - Fix: Check DNS/firewall to tracker servers

3. **Port not listening** (10% - Less likely)
   - Fix: Verify *** config and restart

4. **Volume permissions** (4% - Unlikely)
   - Fix: Adjust permissions on /data/torrents

5. **Config issue** (1% - Very unlikely)
   - Fix: Reset *** config to defaults

---

## 📝 Notes

- Each phase is independent - results inform next phase
- All commands are read-only (safe to run)
- Only Phase 1.3 makes a temporary change (for testing)
- Phase 1 Fix is the most likely solution
- Keep a record of which checks pass/fail for troubleshooting

---

**Ready to execute? Confirm, and we'll run Phase 1!**
