# Homelab

A hybrid k3s cluster spanning AWS EC2 spot instances and Raspberry Pi nodes, reached only over Tailscale, deployed declaratively via Terraform + Ansible + ArgoCD.

> **Documentation:** [`docs/README.md`](docs/README.md) is the single source of truth — start there.

## Architecture

```mermaid
graph TD
    A[Operator] -- make deploy --> B(bin/deploy_aws_homelab.py)

    subgraph Infrastructure
        B -- Terraform --> D[infra/aws/]
        D --> E[2× EC2 Spot + Lambda Scheduler]
    end

    subgraph Configuration
        B -- Ansible --> J[ansible/]
        J -- installs --> K[k3s + Tailscale + ArgoCD]
    end

    subgraph Applications
        K -- ArgoCD syncs --> M[k8s/apps/ in git]
    end

    style A fill:#e6ffed
    style B fill:#e6ffed
    style M fill:#f0f0f0
    style E fill:#fff5e6
```

| Layer | Tooling |
|---|---|
| Infrastructure | Terraform (`infra/aws/`) |
| Configuration | Ansible (`ansible/`, 6 roles) |
| Platform | k3s `v1.34.3+k3s1`, ArgoCD `v2.13.2` |
| Apps | Kustomize manifests synced by ArgoCD App-of-Apps (`k8s/`) |
| Ingress | Tailscale operator (no public ports anywhere) |
| Secrets | SOPS + age encryption |

## Quick Start

```bash
make deploy
```

5-minute step-by-step: [`QUICKSTART.md`](QUICKSTART.md). Cost: ~$24.59/month with the default 11 hr/day schedule (~$45.55/month if you disable scheduling). Detail: [`docs/operations/cost-and-scheduling.md`](docs/operations/cost-and-scheduling.md).

## Common Commands

| Command | Purpose |
|---|---|
| `make help` | Every target with its inline description |
| `make deploy` | Full stack from scratch |
| `make destroy` | Tear down AWS infra (interactive confirm) |
| `make ansible-deploy` | Re-run config, skip Terraform |
| `make terraform-apply` | Re-run Terraform, skip Ansible |
| `make smoke-test` | Post-deploy HTTP checks across all 16 apps |
| `make k8s-nodes` / `make k8s-apps` | kubectl shortcuts |

Full reference: [`docs/reference/makefile-targets.md`](docs/reference/makefile-targets.md).

## Documentation

| Path | What |
|---|---|
| [`docs/README.md`](docs/README.md) | Hub — table of contents for everything |
| [`docs/getting-started/`](docs/getting-started/) | Deployment + prerequisites |
| [`docs/architecture/`](docs/architecture/) | AWS, k3s, GitOps, networking, secrets |
| [`docs/operations/`](docs/operations/) | Terraform, Ansible, testing, SOPS, cost |
| [`docs/services/`](docs/services/) | Per-app docs (16 apps) |
| [`docs/runbooks/`](docs/runbooks/) | On-call recovery |
| [`docs/security/`](docs/security/) | Posture, audit history, fixes backlog |
| [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) | Naming, versioning, doc style |

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the workflow. Adding an Ansible role? Read [`docs/contributing/ansible-roles.md`](docs/contributing/ansible-roles.md) — every role must have Molecule tests; CI rejects roles without them.
