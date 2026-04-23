# Runbook: Tailscale Logged Out (Cluster Unreachable)

| Field | Value |
|:--- |:--- |
| **Severity** | 🟡 Warning (cluster up; just unreachable) |
| **Status** | ✅ Reviewed |
| **Last Tested** | 2026-02-17 |
| **Owner** | @ariel-extending851 |

---

## Symptoms

`kubectl` commands time out, ArgoCD UI is unreachable, all `*.tail57bf10.ts.net` hostnames fail to resolve. The cluster looks down — but if you check via SSM:

```bash
# Via SSM Session Manager
aws ssm start-session --target <k3s-server-instance-id>
sudo systemctl status k3s          # Active: activating (start) — k3s is fine
sudo ss -tlnp | grep :6443         # *:6443 — API server is listening
sudo tailscale status              # Logged out.   ← THE PROBLEM
```

The cluster is alive. Tailscale auth on the control plane node has expired or been revoked, so the tailnet IP (`100.x.x.x:6443`) that your kubeconfig points at is unreachable.

## Root Cause

- Tailscale auth keys expire (default 90 days)
- A reauth event in the Tailscale console can knock a node off
- Tailscale daemon was killed and restarted without persisting state (rare with the `tailscale-state` PVC pattern, but possible on hosts)

## Resolution

You need to re-authenticate Tailscale on the control plane node. Pick the option that matches what credentials you have on hand.

### Option 1 (preferred) — Re-auth via SSM with an auth key

If you have a valid Tailscale auth key (or can generate one at <https://login.tailscale.com/admin/settings/keys>):

```bash
aws ssm send-command \
  --instance-ids <k3s-server-instance-id> \
  --document-name "AWS-RunShellScript" \
  --parameters '{"commands":["sudo tailscale up --authkey tskey-auth-XXXXX --advertise-routes=10.42.0.0/16,10.43.0.0/16"]}' \
  --region us-east-1
```

Get the instance ID from `make terraform-output` (`k3s_server_instance_id`).

### Option 2 — Interactive login via SSM

If you don't have an auth key:

```bash
aws ssm start-session --target <k3s-server-instance-id>
sudo tailscale up --advertise-routes=10.42.0.0/16,10.43.0.0/16
# Follow the auth URL in a browser; approve the device in the Tailscale admin panel
```

### Option 3 — EC2 Instance Connect (web-based shell)

1. AWS Console → EC2 → Instances → select the server → **Connect → EC2 Instance Connect**
2. Run `sudo tailscale up`
3. Open the auth URL in your browser

### Option 4 (last resort) — Public IP SSH

Only if SSM is also broken. **Temporarily** open port 22 from your IP in the security group, then:

```bash
ssh ec2-user@<public-ip>
sudo tailscale up
# After auth: REMOVE the SSH rule from the security group
```

The `infra/aws/modules/network` security group has no public ingress by default — adding it should be a deliberate, time-bounded action.

## Verification

```bash
# 1. Confirm Tailscale is up on the server
aws ssm send-command --instance-ids <id> --document-name "AWS-RunShellScript" \
  --parameters '{"commands":["tailscale status | head -5"]}' --region us-east-1

# 2. From your workstation
ping 100.109.54.24                # the server's tailnet IP — substitute yours
kubectl get nodes
make k8s-nodes
```

Once `kubectl get nodes` returns within 3 seconds, recovery is complete.

## Prevention

- **Use OAuth client credentials** instead of single-device auth keys for the operator install (see [`../services/tailscale-operator.md`](../services/tailscale-operator.md))
- **Persistent auth keys with `--ephemeral=false`** — the server should keep its identity across reboots
- **Add a Prometheus alert** on `node_systemd_unit_state{name="tailscaled.service",state="active"} == 0` — paged before users notice
- **Document the auth key rotation cadence** in your password manager

## Related

- [Control plane recovery](control-plane-recovery.md) — when the cluster *is* actually broken
- [`../architecture/networking.md`](../architecture/networking.md) — how the tailnet fits in
- [`../services/tailscale-operator.md`](../services/tailscale-operator.md) — operator setup
