# Ansible

Configuration management for the homelab. Runs after Terraform; installs k3s, joins nodes to Tailscale, and bootstraps ArgoCD.

For full documentation, see:

- **Operations (run + Phase 2 ArgoCD bootstrap):** [`docs/operations/ansible.md`](../docs/operations/ansible.md)
- **Testing (Molecule):** [`docs/operations/testing.md#molecule-ansible-role-tests`](../docs/operations/testing.md#molecule-ansible-role-tests)
- **SOPS workflow:** [`docs/operations/sops-setup.md`](../docs/operations/sops-setup.md)
- **GitOps architecture:** [`docs/architecture/gitops.md`](../docs/architecture/gitops.md)
- **New role checklist:** [`docs/contributing/role-template.md`](../docs/contributing/role-template.md)

## Layout

| Path | Purpose |
|---|---|
| `playbooks/site.yml` | Master playbook (runs all phases) |
| `playbooks/gitops/` | ArgoCD install + apps-root bootstrap |
| `playbooks/maintenance/` | Health checks, cleanup, RPi optimization |
| `playbooks/recovery/` | Emergency recovery scenarios |
| `roles/` | 6 roles: k3s, tailscale, argocd, gatekeeper, rpi_optimization, emergency_recovery |
| `roles/.template/` | Skeleton for new roles |
| `inventory/production.yml` | Static inventory (Pis, router, workstation) |
| `inventory/terraform_inventory_aws.py` | Dynamic inventory (AWS instances from Terraform state) |
| `group_vars/` | Per-group variables (k3s_server, raspberry_pi, gatekeeper, router) |

## Quick start

```bash
make ansible-ping        # connectivity check
make ansible-check       # dry-run
make ansible-deploy      # full site.yml
```
