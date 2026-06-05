# Pi-only Deployment

How to deploy the homelab with only the Raspberry Pis — no AWS EC2, no
Terraform, no SSM. The hybrid AWS+Pi path stays intact as a rollback.

## When to use this

- AWS account is torn down (post-`make destroy`, e.g. cost-zero days).
- You want to bring AdGuard and the media stack back online without paying
  for a spot instance.
- You're validating a change locally on the Pis before re-enabling AWS.

## Architecture

| Node         | Role                | Network                                 | Notes                                              |
|--------------|---------------------|-----------------------------------------|----------------------------------------------------|
| `rasp-pi-04` | k3s server + ArgoCD | LAN `192.168.8.11`, TS `100.84.176.35`  | 8 GB RPi4. Hosts Tailscale operator + all proxies. |
| `rasp-pi-03` | k3s agent           | LAN `192.168.8.12`, TS `100.75.83.105`  | 1 GB RPi3. Dedicated to AdGuard (host port 53).    |

- Pi-to-Pi traffic flows over LAN `eth0` (flannel VXLAN). Cross-Pi traffic
  over Tailscale is currently broken (see
  [`k8s/system/tailscale-operator/proxyclass.yaml`](../../k8s/system/tailscale-operator/proxyclass.yaml)).
- Tailscale is still used for **remote** kubectl access from a developer
  laptop to `rasp-pi-04:6443`.
- The `tailscale-operator` ProxyClass already pins all Tailscale ingress
  proxies to `rasp-pi-04`, so AdGuard's 1 GB neighbour stays light.

## Prerequisites

Both Pis must already be:

1. Running Ubuntu 22.04+ (arm64), reachable on LAN at the IPs above.
2. SSH-accessible as `ubuntu` with passwordless sudo and your deploy key
   in `authorized_keys`.
3. Joined to Tailscale (`tailscale up` already authenticated). The k3s role
   does **not** install or auth Tailscale — that's a one-time manual step.

On your control machine you need:

- `~/.config/sops/age/keys.txt` with the age private key (the same one
  `infra/aws/terraform.tfvars.sops.yaml` is encrypted to).
- `~/.ssh/homelab-deploy-key` (the SSH key ArgoCD uses for the private
  media repo referenced by `argocd_extra_repo_url` in
  `ansible/group_vars/k3s_server.sops.yml`).
- `mise install` already run, so `ansible-playbook`, `sops`, and `kubectl`
  are all on `$PATH`.

## Procedure

```bash
make pi-only-deploy
```

That runs [`bin/deploy_pi_homelab.py`](../../bin/deploy_pi_homelab.py),
which does three phases:

1. **prerequisites** — checks `sops`, `ansible-playbook`, `ssh`, that both
   `inventory/production.yml` and `inventory/pi-only.yml` exist, and that
   every `k8s/**/secret.yaml` decrypts cleanly.
2. **ansible** — runs the full `playbooks/site.yml` against the layered
   inventory:

   ```bash
   ansible-playbook -i inventory/production.yml \
                    -i inventory/pi-only.yml \
                    playbooks/site.yml
   ```
   This goes through Phase 0 (cleanup), Phase 1 (Tailscale, RPi tuning,
   k3s server install on pi-04, k3s agent install on pi-03), Phase 2
   (ArgoCD bootstrap + app-of-apps + `argocd_extra_repo_url` from SOPS),
   and Phase 3 (verification).
3. **verify** — slurps `/etc/rancher/k3s/k3s.yaml` from `rasp-pi-04` over
   SSH, rewrites `127.0.0.1` → `100.84.176.35`, writes
   `/tmp/k3s-homelab-kubeconfig.yaml` (mode `0600`).

Estimated total time: **20–30 min** on first run.

The script uses `.deploy-state.json` for resume, so a re-run after a
partial failure can use `--resume-from=ansible` or `--resume-from=verify`
to skip already-completed phases (state expires after 2 hours).

## Verification

```bash
export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml

# 1. Both nodes Ready
kubectl get nodes -o wide
# Expect:
#   rasp-pi-04   Ready   control-plane,master   ...
#   rasp-pi-03   Ready   <none>                 ...

# 2. ArgoCD root apps synced
kubectl get applications -n argocd
# Expect homelab-apps-root and homelab-media-root: Synced + Healthy

# 3. AdGuard still pinned to pi-03
kubectl -n adguard get pod -o wide | grep rasp-pi-03

# 4. Tailscale proxies on pi-04 only
kubectl -n tailscale get pod -o wide | awk 'NR>1{print $7}' | sort -u

# 5. apiserver TLS SAN covers both LAN and Tailscale
ssh ubuntu@192.168.8.11 \
  "sudo openssl x509 -in /var/lib/rancher/k3s/server/tls/serving-kube-apiserver.crt -noout -text" \
  | grep -A1 'Subject Alternative Name'

# 6. Memory headroom on pi-04 (8 GB total, baseline ~3 GB)
kubectl top node rasp-pi-04
```

## Rollback to hybrid AWS+Pi

Pi-only is non-destructive to the hybrid path: nothing in
`inventory/production.yml`, the `k3s` role, or the AWS Terraform module
was rewritten. To return:

1. Re-provision AWS: `cd infra/aws && terraform apply` (or
   `make terraform-apply`).
2. Run the hybrid deploy: `make deploy` (or
   `python3 bin/deploy_aws_homelab.py`). The AWS dynamic inventory injects
   the EC2 control plane into `k3s_server`; `rasp-pi-04`'s pi-only
   overrides only load when `inventory/pi-only.yml` is included, so it
   demotes back to agent automatically. The `install_agent.yml` Case B
   logic (lines 49–92) detects the prior server install on pi-04, runs
   `k3s-uninstall.sh`, and re-joins as agent.

## Operational tradeoffs

- **Single point of failure on `rasp-pi-04`.** Control plane, ArgoCD, and
  all Tailscale proxies live there. If pi-04 dies, the cluster API and
  all Tailscale ingresses go down. AdGuard on pi-03 keeps serving DNS
  because it uses `hostNetwork` and the GL.iNet router has a cron-based
  fallback to public DNS.
- **No HA.** k3s runs with the default sqlite datastore (`cluster-init:
  false`). Note: k3s's native etcd snapshots do **not** work on sqlite — the
  `etcd-snapshot-*` flags are inert there (the server-config template now
  suppresses them and says so). Control-plane backup is instead handled by the
  **`k8s/apps/k3s-snapshot` CronJob**, which uploads a gzipped `sqlite3 .backup`
  of `state.db` to `s3://homelab-velero-backups-kkuhocyv/cluster-state/` every
  12h. Restore: [`docs/runbooks/control-plane-snapshot-restore-pi.md`](../runbooks/control-plane-snapshot-restore-pi.md).
  (Etcd on an SD card is a write-amplification anti-pattern, so we keep sqlite +
  offsite snapshots rather than migrating to embedded etcd.)
- **Memory headroom on pi-04 is tight if the private media stack lands
  there.** Baseline (k3s + ArgoCD + ~11 Tailscale proxies + kube-system)
  is ~3 GB. Adding jellyfin/*arr can push past 6 GB. Set explicit memory
  limits in the media app manifests.
- **`rasp-pi-03` has only ~400–500 MB free** after AdGuard + kubelet +
  k3s-agent. Avoid scheduling any extra DaemonSets there. If you must,
  add a `dedicated=adguard:NoSchedule` taint and tolerate it only on
  AdGuard.
- **Tailscale ACL gap (`tag:rpi` self-rule)** in
  [`infra/aws/acl.json`](../../infra/aws/acl.json) does not affect this
  mode because Pi-to-Pi traffic stays on LAN. Land the ACL fix before
  re-enabling hybrid AWS+Pi.
