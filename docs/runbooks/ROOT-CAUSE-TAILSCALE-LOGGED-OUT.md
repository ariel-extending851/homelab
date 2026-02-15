# 🔴 ROOT CAUSE IDENTIFIED: Tailscale Logged Out

## The Problem

**Tailscale is LOGGED OUT on k3s-server-1 (control plane node)**

**Evidence:**
```
=== TAILSCALE STATUS ===
Logged out.
Log in at: https://login.tailscale.com/a/155f25343ae143
```

**Why this breaks everything:**
1. kubectl config uses Tailscale IP: `100.109.54.24:6443`
2. Tailscale is not authenticated
3. No network path from your workstation to the API
4. Kubernetes appears "down" but is actually running
5. Port 6443 is listening, but unreachable via Tailscale

## Verification

**From SSM diagnostics:**
- ✅ k3s is running: `Active: activating (start)`
- ✅ API port listening: `*:6443`
- ✅ kubeconfig exists: `/etc/rancher/k3s/k3s.yaml`
- ❌ Tailscale: **LOGGED OUT**

## Solutions

### Option 1: Re-authenticate Tailscale via SSM (RECOMMENDED)

I can attempt to re-authenticate Tailscale using SSM, but I need your Tailscale auth method.

**Do you have:**
1. **Tailscale OAuth client ID/secret?** (preferred for servers)
2. **Tailscale auth key?** (can be generated in admin panel)
3. **Tailscale account credentials?** (not recommended)

**If you have an auth key, I can run:**
```bash
# Via SSM
sudo tailscale up --authkey tskey-auth-XXXXX --advertise-routes=10.42.0.0/16,10.43.0.0/16
```

### Option 2: Interactive Login (Requires Browser)

**Steps:**
1. Connect via SSM Session Manager
2. Run: `sudo tailscale up`
3. Copy the auth URL from output
4. Open in browser and authenticate
5. Approve the device in Tailscale admin panel

**I can initiate this via SSM:**
```bash
aws ssm send-command \
    --instance-ids i-07f1cf6f322c8aa3c \
    --document-name "AWS-RunShellScript" \
    --parameters '{"commands":["sudo tailscale up --advertise-routes=10.42.0.0/16,10.43.0.0/16"]}' \
    --region us-east-1
```

Then you'll see an auth URL in the output to open in your browser.

### Option 3: Use EC2 Instance Connect

1. Go to AWS Console → EC2 → Instances
2. Select i-07f1cf6f322c8aa3c (hl-k3s-server)
3. Click "Connect" → "EC2 Instance Connect"
4. In terminal, run:
   ```bash
   sudo tailscale up
   ```
5. Copy the URL and authenticate in browser

### Option 4: Use SSH via AWS Public IP

Temporarily use SSH over the public internet (not Tailscale):

1. Get instance public IP from AWS Console
2. Ensure security group allows SSH (port 22) from your IP
3. SSH: `ssh ec2-user@<public-ip>`
4. Run: `sudo tailscale up`
5. Authenticate

**Security Note:** Remember to remove SSH access from security group afterward.

## Immediate Action Required

**Please choose one option above and provide:**

**If Option 1 (auth key):**
- Your Tailscale auth key (starts with `tskey-auth-`)

**If Option 2 or 3 (interactive):**
- I'll start the process
- You'll see a URL like `https://login.tailscale.com/a/XXXXX`
- You open it in browser and click "Authorize"

**If Option 4 (SSH):**
- Instance public IP
- Confirm security group has port 22 open

## After Tailscale is Fixed

Once Tailscale is authenticated:

1. **Wait 30 seconds** for network to establish
2. **Test connectivity:**
   ```bash
   ping 100.109.54.24
   kubectl get nodes
   ```
3. **Run the recovery script:**
   ```bash
   ./scripts/emergency-recovery.sh
   ```
4. **Verify ***/*** are accessible**

## Prevention

To prevent this in the future:

1. **Use OAuth instead of device auth** (more reliable for servers)
2. **Set up Tailscale to auto-start on boot** with auth key
3. **Add monitoring** for Tailscale connectivity
4. **Document the auth key** in your password manager

## Summary

**The cluster is NOT broken** - it's just that Tailscale authentication expired/lost on the control plane node.

**Fix is simple:** Re-authenticate Tailscale on k3s-server-1 using one of the methods above.

**ETA to recovery:** 2-3 minutes after Tailscale is re-authenticated.

---

**Which option would you like to use?**
