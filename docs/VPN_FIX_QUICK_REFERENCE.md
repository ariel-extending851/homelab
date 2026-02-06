# 🚀 VPN Fix - Quick Reference Card

**Time Required:** 20 minutes
**Difficulty:** Medium
**Full Guide:** See `VPN_FIX_IMPLEMENTATION_PLAN.md`

---

## 📋 Quick Checklist

```
□ 1. Regenerate *** WireGuard key (5 min)
     → https://***.net/en/account/
     → Delete old key → Generate new → Copy private key + IP

□ 2. Update Kubernetes secret (5 min)
     → kubectl edit secret ***-secret -n media
     → Update WIREGUARD_PRIVATE_KEY and WIREGUARD_ADDRESSES

□ 3. Fix deployment YAML (2 min)
     → Add: WIREGUARD_ALLOWED_IPS: "0.0.0.0/0"
     → After line: VPN_IPV6: "off"

□ 4. Apply changes (3 min)
     → kubectl apply -f k8s/apps/***/deployment.yaml

□ 5. Verify VPN working (5 min)
     → Check logs, test public IP, verify routing

□ 6. Test torrents (5 min)
     → Resume torrent → Check seeds/peers → Verify download speed
```

---

## ⚡ Copy-Paste Commands

### Base64 Encode (Step 2)
```bash
# Encode private key
echo -n 'YOUR_***_PRIVATE_KEY' | base64

# Encode IP address
echo -n 'YOUR_***_IP_ADDRESS' | base64
```

### Update Secret (Step 2)
```bash
kubectl edit secret ***-secret -n media
# Replace WIREGUARD_PRIVATE_KEY and WIREGUARD_ADDRESSES with base64 values
```

### Deployment Change (Step 3)
Add after `VPN_IPV6: "off"`:
```yaml
            # Force IPv4-only routing to avoid IPv6 conflicts
            - name: WIREGUARD_ALLOWED_IPS
              value: "0.0.0.0/0"
```

### Apply Changes (Step 4)
```bash
kubectl apply -f k8s/apps/***/deployment.yaml
kubectl get pods -n media -l app=*** -w
```

### Verify VPN (Step 5)
```bash
export QB_POD=$(kubectl get pod -n media -l app=*** -o jsonpath='{.items[0].metadata.name}')

# Check public IP
kubectl exec -n media $QB_POD -c *** -- curl -s http://127.0.0.1:8000/v1/publicip/ip

# Should return: {"public_ip":"193.32.127.XXX","country":"Switzerland",...}
```

---

## ✅ Success Indicators

| What to Check | Expected Result |
|--------------|----------------|
| *** logs | "Public IP address is 193.32.127.XXX" |
| Public IP test | Country: Switzerland |
| Routing | `default dev tun0` |
| *** UI | Seeds > 0, Peers > 0 |
| Download speed | > 0 B/s |

---

## 🆘 Quick Troubleshooting

### Still not connecting?
```bash
# Force clean restart
kubectl delete pod -n media $QB_POD

# Wait and re-test
kubectl wait --for=condition=ready pod -l app=*** -n media --timeout=180s
```

### Wrong credentials?
- Double-check *** dashboard
- Verify no extra spaces in base64 encoding
- Re-run Step 2

### Emergency rollback?
```bash
# Disable kill switch temporarily
kubectl set env deployment/*** -n media -c *** FIREWALL=off
```

---

## 📞 Where to Get Help

- **Full Guide:** `docs/VPN_FIX_IMPLEMENTATION_PLAN.md`
- ***** FAQ:** https://github.com/qdm12/***-wiki/blob/main/faq/healthcheck.md
- ***** Check:** https://***.net/en/check

---

**Ready to start? Open the full guide and follow each step carefully!**
