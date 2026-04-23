# Deployment

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

End-to-end deployment guide. For the 5-minute teaser, see the root [`QUICKSTART.md`](../../QUICKSTART.md). Prerequisites are in [`prerequisites.md`](prerequisites.md).

---

## What This Does

A single `make deploy` runs the entire stack:

1. **Terraform** provisions AWS (VPC, security groups, IAM, 2× EC2 spot instances, scheduler Lambda) — 3–5 min
2. **Wait** for instances to boot and SSM to be ready — 2–5 min
3. **Ansible** configures k3s, installs ArgoCD with the SOPS plugin, applies the GitHub deploy key, bootstraps the App-of-Apps — 10–18 min
4. **Verify** kubeconfig retrieval, cluster health, ArgoCD sync state — 1 min

Total: **15–25 minutes** unattended.

---

## Three Ways to Deploy

### Option 1 — One command (recommended)

```bash
make deploy
```

Runs [`bin/deploy_aws_homelab.py`](../../bin/deploy_aws_homelab.py) which orchestrates Terraform + Ansible with proper waits and rollback hooks.

### Option 2 — Python script directly

```bash
chmod +x bin/deploy_aws_homelab.py
python3 bin/deploy_aws_homelab.py
```

### Option 3 — Manual (educational / debugging)

```bash
# 1. AWS infrastructure
cd infra/aws
terraform init
terraform apply -auto-approve

# 2. Wait for SSH
SERVER_IP=$(terraform output -raw k3s_server_public_ip)
until ssh -i ~/.ssh/homelab-aws ec2-user@$SERVER_IP "echo ready"; do sleep 10; done

# 3. Ansible
cd ../../ansible
ansible-playbook -i inventory/ playbooks/site.yml

# 4. Kubeconfig
ssh -i ~/.ssh/homelab-aws ec2-user@$SERVER_IP "sudo cat /etc/rancher/k3s/k3s.yaml" \
  | sed "s|127.0.0.1|$SERVER_IP|g" > ~/.kube/homelab-config
export KUBECONFIG=~/.kube/homelab-config
kubectl get nodes
```

In day-to-day operation, prefer Option 1 — `make deploy` is identical to what CI runs.

---

## Phase Walkthrough

### Phase 1 — Terraform (3–5 min)

Creates VPC, security groups, IAM roles, 2× EC2 spot instances (t3.medium server + t3.small agent), Lambda scheduler, EventBridge rules. SOPS-encrypted `terraform.tfvars.sops.yaml` provides SSH key, k3s token, Tailscale auth key.

Variables and module breakdown: [`../architecture/aws-infrastructure.md`](../architecture/aws-infrastructure.md).

### Phase 2 — Wait for instances (2–5 min)

The deploy script polls SSH on the public IPs (or SSM session, if Tailscale isn't yet up) until both nodes accept connections.

### Phase 3 — Ansible configure (10–18 min)

Runs `ansible/playbooks/site.yml` which orchestrates 4 sub-phases:

| Phase | What |
|---|---|
| 1.1 | RPi optimization (skipped on AWS-only deploy) |
| 1.2 | k3s install (server + agent), Tailscale join |
| 2.1 | ArgoCD install + SOPS CMP plugin + GitHub deploy key |
| 2.2 | Apply `apps-root` Application — ArgoCD takes over from here |
| 3 | Verification: nodes Ready, ArgoCD pods 5/5, apps-root Synced+Healthy |

Roles, playbooks, inventory: [`../operations/ansible.md`](../operations/ansible.md).

### Phase 4 — Verify & summary (~1 min)

Kubeconfig saved to `/tmp/k3s-homelab-kubeconfig.yaml`. Output prints instance IPs, ArgoCD admin password, and the URLs to access the UI.

---

## Verification

```bash
export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml

# 1. Nodes
kubectl get nodes -o wide
# expect: k3s-server-1 + k3s-agent-2 (Ready); rasp-pi-03 + rasp-pi-04 (Ready) if home LAN reachable

# 2. ArgoCD
kubectl get pods -n argocd
# expect: all Running; argocd-repo-server should show 2/2 (main + sops-plugin sidecar)

kubectl get application homelab-apps-root -n argocd
# expect: Synced + Healthy

# 3. Per-app sync
kubectl get applications -n argocd
# all child apps should be Synced + Healthy after 5–15 min

# 4. Smoke test (after ArgoCD finishes)
make smoke-test
# 0 = pass, 2 = minor issues, 1 = fail
```

---

## Access ArgoCD UI

```bash
# Admin password
make argocd-password
# or:
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo

# Port-forward
make argocd-port-forward
# https://localhost:8080
# username: admin
```

---

## Cost

With the default scheduler (10:00–21:00 BRT) the AWS bill is **~$24.59/month**. Set `enable_scheduling = false` in `infra/aws/terraform.tfvars` to run 24/7 (~$45.55/month). Full breakdown and the resolution of older/conflicting cost numbers: [`../operations/cost-and-scheduling.md`](../operations/cost-and-scheduling.md).

---

## Common Operations

```bash
make destroy             # tear down AWS infra (interactive confirm)
make ansible-deploy      # re-configure without re-running Terraform
make ansible-health      # cluster health check
make smoke-test          # post-deploy smoke
make test-e2e-post-deploy # full E2E (40+ Bats cases)
```

---

## Troubleshooting

### Deployment fails
The script is idempotent — re-run:
```bash
python3 bin/deploy_aws_homelab.py
```
Most common: SSH not yet ready (Phase 2 timeout). Check `aws ec2 describe-instances` for state, or use `aws ssm start-session` instead.

### Can't SSH to instances
Public SSH is **not allowed** by default. Use Tailscale (after Phase 3) or AWS SSM Session Manager:
```bash
aws ssm start-session --target $(make terraform-output | jq -r '.k3s_server_instance_id.value')
```

### ArgoCD apps stuck in `Progressing`
```bash
kubectl describe application <name> -n argocd
kubectl get applications -n argocd -o name | xargs -I {} kubectl patch {} -n argocd \
  --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

For a Tailscale auth issue blocking the cluster, see [`../runbooks/tailscale-logged-out.md`](../runbooks/tailscale-logged-out.md). For control plane unresponsive, see [`../runbooks/control-plane-recovery.md`](../runbooks/control-plane-recovery.md).

---

## Related

- **Prerequisites:** [`prerequisites.md`](prerequisites.md)
- **AWS architecture:** [`../architecture/aws-infrastructure.md`](../architecture/aws-infrastructure.md)
- **GitOps detail:** [`../architecture/gitops.md`](../architecture/gitops.md)
- **Ansible deep-dive:** [`../operations/ansible.md`](../operations/ansible.md)
- **Cost & scheduler:** [`../operations/cost-and-scheduling.md`](../operations/cost-and-scheduling.md)
- **SOPS workflow:** [`../operations/sops-setup.md`](../operations/sops-setup.md)
