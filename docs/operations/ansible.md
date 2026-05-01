# Ansible Operations

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Ansible runs **after** Terraform. It installs k3s, joins nodes to the tailnet, and bootstraps ArgoCD with the SOPS plugin. From there, ArgoCD takes over.

---

## TL;DR

```bash
make ansible-ping        # connectivity check
make ansible-check       # dry-run the entire site.yml
make ansible-deploy      # run site.yml (full deployment)
```

The Makefile targets handle inventory paths and `mise exec`. To run the playbooks directly:

```bash
cd ansible
ansible-playbook -i inventory/production.yml playbooks/site.yml
```

---

## Roles

There are **6 roles** under [`ansible/roles/`](../../ansible/roles/). All have Molecule test scenarios.

| Role | Purpose | Key vars |
|---|---|---|
| [`k3s`](../../ansible/roles/k3s) | Install k3s server (control plane) or agent (worker) | `k3s_version`, `k3s_token`, `k3s_server_url` |
| [`tailscale`](../../ansible/roles/tailscale) | Install + auth Tailscale on every node | `tailscale_auth_key` (SOPS) |
| [`argocd`](../../ansible/roles/argocd) | Install ArgoCD, mount age key as `sops-age` Secret, patch repo-server with SOPS CMP, install GitHub deploy key | `argocd_version`, `git_repo_url`, `argocd_namespace` |
| [`gatekeeper`](../../ansible/roles/gatekeeper) | Configure the Opal OpenWrt router (Wi-Fi SSIDs, ACLs) | `wifi_password` (SOPS) |
| [`rpi_optimization`](../../ansible/roles/rpi_optimization) | Tune kernel params, swap, CPU governor, I/O scheduler on Raspberry Pi nodes | `rpi_swap_size`, `rpi_cpu_governor` |
| [`emergency_recovery`](../../ansible/roles/emergency_recovery) | Failover scenarios and recovery guardrails (used by `recovery/emergency_recovery.yml`) | — |

The Copier template for new roles lives in [`templates/ansible-role/`](../../templates/ansible-role/) (invoked via `make new-role`). See [`../contributing/role-template.md`](../contributing/role-template.md) for the checklist.

---

## Playbooks

The hub is `playbooks/site.yml` — it orchestrates the full deployment in 4 phases.

| Playbook | Phase / purpose |
|---|---|
| [`site.yml`](../../ansible/playbooks/site.yml) | Master playbook: pre-cleanup → infrastructure → GitOps → verification |
| [`deploy_k3s.yml`](../../ansible/playbooks/deploy_k3s.yml) | Just k3s (server + agents) |
| [`gitops/deploy_argocd.yml`](../../ansible/playbooks/gitops/deploy_argocd.yml) | Install ArgoCD + SOPS plugin (Phase 2) |
| [`gitops/bootstrap_apps.yml`](../../ansible/playbooks/gitops/bootstrap_apps.yml) | Apply `apps-root.yaml` so ArgoCD takes over |
| [`configure_router.yml`](../../ansible/playbooks/configure_router.yml) | Run gatekeeper role on the Opal router |
| [`validation.yml`](../../ansible/playbooks/validation.yml) | Read-only checks across the cluster |
| [`maintenance/health_check.yml`](../../ansible/playbooks/maintenance/health_check.yml) | API server, kubelet, Tailscale daemon health |
| [`maintenance/cleanup_tailscale.yml`](../../ansible/playbooks/maintenance/cleanup_tailscale.yml) | Prune stale tailnet nodes via Tailscale API |
| [`maintenance/optimize_rpi.yml`](../../ansible/playbooks/maintenance/optimize_rpi.yml) | Apply rpi_optimization to existing Pi nodes |
| [`recovery/emergency_recovery.yml`](../../ansible/playbooks/recovery/emergency_recovery.yml) | Cluster failure recovery procedures |

### `site.yml` phases

| Phase | What |
|---|---|
| 0 — Pre-migration cleanup | Demote a Pi server to agent if needed (legacy) |
| 1 — Infrastructure | Tailscale on every node, k3s install, RPi optimization |
| 2 — GitOps | ArgoCD install + SOPS CMP + GitHub deploy key |
| 3 — Verification | Pod health, ArgoCD sync, ingress reachability |

---

## Inventory

Two layers, merged at runtime.

### Static inventory: [`inventory/production.yml`](../../ansible/inventory/production.yml)

Defines the always-on nodes (Raspberry Pis + router + workstation) and the group hierarchy:

```text
all
├── raspberry_pi: rasp-pi-03, rasp-pi-04
├── k3s_agent: (Pi nodes + AWS agent at runtime)
├── k3s_server: (AWS server, dynamic)
├── arm_nodes: (rasp-pi-03, rasp-pi-04)
├── storage_nodes: rasp-pi-04
├── low_memory_nodes: rasp-pi-03
├── router: opal-gateway (192.168.8.1)
└── workstations: pc-tower
```

### Dynamic inventory: [`inventory/terraform_inventory_aws.py`](../../ansible/inventory/terraform_inventory_aws.py)

Reads Terraform state and adds the live AWS instances to `k3s_server` and `k3s_agent` groups, addressed by their Tailscale IPs.

```bash
cd ansible
ansible-inventory -i inventory/production.yml --graph        # static only
ansible-inventory -i inventory/terraform_inventory_aws.py --graph    # dynamic only
ansible-inventory -i inventory/ --graph                      # merged (Make target uses this)
```

### Group vars

| File | What it sets |
|---|---|
| [`group_vars/all.yml`](../../ansible/group_vars/all.yml) | k3s version + CIDRs, Tailscale tailnet, app namespaces, common packages, log rotation |
| [`group_vars/k3s_server.yml`](../../ansible/group_vars/k3s_server.yml) | ArgoCD version, namespace, SOPS age public key, git repo URL |
| [`group_vars/raspberry_pi.yml`](../../ansible/group_vars/raspberry_pi.yml) | RPi-specific kubelet args, swap, CPU governor, thermal thresholds |
| `group_vars/gatekeeper.sops.yml` | Encrypted Wi-Fi credentials |
| `group_vars/router.sops.yml` | Encrypted router admin credentials |

> **k3s_server.yml** also pins `git_repo_url: "git@github.com:ariel-extending851/homelab.git"` (the canonical repo URL — `ariel99gf` is the old name).

---

## ArgoCD Bootstrap (Phase 2 Detail)

This is the one playbook with the most state — it sets up the GitOps pipeline that runs everything else.

### Prerequisites

1. **Python `kubernetes` library** on the workstation: `pip3 install kubernetes`
2. **Ansible collections**: `ansible-galaxy collection install -r ansible/requirements.yml`
3. **SOPS age key** at `~/.config/sops/age/keys.txt` matching `age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja`
4. **GitHub deploy key** for the repo:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/homelab-deploy-key -C "argocd@homelab" -N ""
   cat ~/.ssh/homelab-deploy-key.pub
   # Add to https://github.com/ariel-extending851/homelab/settings/keys
   ssh -T -i ~/.ssh/homelab-deploy-key git@github.com   # confirm "successfully authenticated"
   ```
5. **k3s cluster reachable**: `ansible k3s_server -i ansible/inventory/ -m ping`

### Run

```bash
# Full Phase 2 (idempotent)
cd ansible
ansible-playbook -i inventory/production.yml playbooks/gitops/deploy_argocd.yml
ansible-playbook -i inventory/production.yml playbooks/gitops/bootstrap_apps.yml
```

Or as part of `site.yml`:
```bash
make ansible-deploy
```

### Verify

```bash
kubectl get pods -n argocd
# argocd-repo-server should show 2/2 (main + sops-plugin sidecar)

kubectl get applications -n argocd
# homelab-apps-root should be Synced + Healthy
```

```bash
# ArgoCD admin password
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo

# Port-forward UI
make argocd-port-forward     # https://localhost:8080
```

Expected timing for first deployment: 13–28 min (k3s install dominates). Subsequent runs: 5–10 min.

---

## Common Tasks

### Health check across the cluster

```bash
make ansible-health
```

### Re-tune all RPi nodes

```bash
ansible-playbook -i inventory/production.yml playbooks/maintenance/optimize_rpi.yml
```

### Prune stale Tailscale nodes

```bash
make clean-tailscale
```

### Configure the router

```bash
make ansible-router
```

### Emergency recovery

```bash
make ansible-emergency
```

---

## Troubleshooting

### `Module 'kubernetes' not found`
```bash
pip3 install kubernetes
```

### `Collection kubernetes.core not found`
```bash
ansible-galaxy collection install kubernetes.core
```

### `argocd-repo-server` shows 1/2 Ready
SOPS sidecar didn't start. Check:
```bash
kubectl logs -n argocd deployment/argocd-repo-server -c sops-plugin
kubectl describe deployment argocd-repo-server -n argocd | grep -A5 sops-age
```

### `Repository authentication failed` (ArgoCD)
The deploy key on GitHub doesn't match the key the playbook installed. Re-run:
```bash
ansible-playbook -i inventory/production.yml playbooks/gitops/deploy_argocd.yml --tags=ssh-key
```

### Application stuck in `Progressing`
```bash
kubectl describe application <app-name> -n argocd
kubectl patch application <app-name> -n argocd --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### SOPS decryption failed inside the cluster
```bash
kubectl exec -n argocd deployment/argocd-repo-server -c sops-plugin -- \
  sh -c 'echo "test" | sops --decrypt /dev/stdin 2>&1'
```

If this errors with "no identity matched any recipient", the `sops-age` Secret has the wrong key. Re-run the argocd role with `--tags=sops-key`.

---

## Testing Roles Locally

Every role has a Molecule scenario. Run all of them:

```bash
make test-molecule
```

Per-role:
```bash
make test-molecule-k3s
make test-molecule-argocd
make test-molecule-rpi
# etc
```

Detail and ARM64 matrix: [`testing.md#molecule`](testing.md#molecule).

### Idempotency check

Beyond Molecule's per-scenario idempotence assertion, the playbook is exercised end-to-end by:

```bash
make test-ansible-idempotency
```

This runs `site.yml` twice against the test target and asserts the second run reports zero `changed` tasks. Backed by [`bin/check_molecule_idempotence.py`](../../bin/check_molecule_idempotence.py). New roles added via `make new-role` inherit an idempotency assertion in their Molecule scenario.

---

## Related

- **Role template (for new roles):** [`../contributing/role-template.md`](../contributing/role-template.md)
- **SOPS workflow:** [`sops-setup.md`](sops-setup.md)
- **Cluster recovery:** [`../runbooks/control-plane-recovery.md`](../runbooks/control-plane-recovery.md)
- **GitOps architecture:** [`../architecture/gitops.md`](../architecture/gitops.md)
