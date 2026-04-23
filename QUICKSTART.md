# Quickstart — 5 Minutes to Deploy

For the impatient: get the homelab running in one command. For the full guide see [`docs/getting-started/deployment.md`](docs/getting-started/deployment.md).

---

## Prerequisites (one-time)

```bash
# 1. Install all tools (mise reads .mise.toml)
curl https://mise.jdx.dev/install.sh | sh
mise install

# 2. Ansible collections
ansible-galaxy collection install -r ansible/requirements.yml

# 3. Python deps
pip3 install kubernetes

# 4. AWS credentials (mise auto-sets AWS_PROFILE=homelab inside the repo)
aws configure --profile homelab

# 5. SSH keys
ssh-keygen -t ed25519 -f ~/.ssh/homelab-aws -N ""
ssh-keygen -t ed25519 -f ~/.ssh/homelab-deploy-key -C "argocd@homelab" -N ""

# 6. SOPS age key (must match age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja)
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt   # see docs/operations/sops-setup.md if mismatch
```

Full prereqs checklist: [`docs/getting-started/prerequisites.md`](docs/getting-started/prerequisites.md).

---

## Deploy

```bash
make deploy
```

Or directly:
```bash
python3 bin/deploy_aws_homelab.py
```

Time: **15–25 minutes** unattended. Phases: Terraform → wait for SSH → Ansible (k3s + ArgoCD) → bootstrap apps → verify.

---

## Verify

```bash
export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml

kubectl get nodes                 # 2 AWS + 2 RPi (if home LAN reachable)
kubectl get applications -n argocd
make smoke-test                   # post-deploy HTTP checks (16 apps)
```

---

## Access ArgoCD

```bash
make argocd-password
make argocd-port-forward          # https://localhost:8080
```

Username: `admin`. Password from `make argocd-password`.

---

## Common Operations

```bash
make destroy             # tear down AWS infra
make ansible-deploy      # re-run config without Terraform
make ansible-health      # cluster health check
make help                # every target with description
```

---

## Cost

| Mode | Estimate |
|---|---|
| With scheduling (default, ~45% uptime) | **~$24.59/month** |
| 24/7 (`enable_scheduling = false`) | ~$45.55/month |

Schedule: starts EC2 at 10:00 BRT, stops at 21:00 BRT (no DST in Brazil since 2019). Full breakdown: [`docs/operations/cost-and-scheduling.md`](docs/operations/cost-and-scheduling.md).

---

## Troubleshooting

### Deployment fails
The script is idempotent — re-run:
```bash
python3 bin/deploy_aws_homelab.py
```

### Can't SSH to instances
There's no public SSH. Use Tailscale (after the deploy completes), or AWS SSM:
```bash
aws ssm start-session --target $(make terraform-output | jq -r '.k3s_server_instance_id.value')
```

### ArgoCD apps stuck in `Progressing`
```bash
kubectl get applications -n argocd -o name | xargs -I {} kubectl patch {} -n argocd \
  --type merge -p '{"operation":{"sync":{"revision":"HEAD"}}}'
```

For a Tailscale auth issue making the cluster unreachable: [`docs/runbooks/tailscale-logged-out.md`](docs/runbooks/tailscale-logged-out.md). For control plane unresponsive: [`docs/runbooks/control-plane-recovery.md`](docs/runbooks/control-plane-recovery.md).

---

## Next Steps

- **Full deployment guide:** [`docs/getting-started/deployment.md`](docs/getting-started/deployment.md)
- **Documentation hub:** [`docs/README.md`](docs/README.md)
- **Per-app details:** [`docs/services/README.md`](docs/services/README.md)
- **Architecture overview:** [`docs/architecture/overview.md`](docs/architecture/overview.md)
