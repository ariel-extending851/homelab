# Homelab Documentation

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Single source of truth for the homelab project. The repo runs a hybrid k3s cluster (AWS EC2 + Raspberry Pi) reached via Tailscale, deployed with Terraform + Ansible + ArgoCD.

If you're new, start with the root [`README.md`](../README.md), then [`getting-started/deployment.md`](getting-started/deployment.md). For any specific app, jump to [`services/`](services/). For naming and doc style, see [`CONVENTIONS.md`](CONVENTIONS.md).

---

## 🚀 Getting Started

| Document | Purpose |
|---|---|
| [Project README](../README.md) | High-level project overview (root entry) |
| [Quickstart](../QUICKSTART.md) | 5-minute deployment path |
| [Deployment Guide](getting-started/deployment.md) | Comprehensive AWS deployment |
| [Prerequisites](getting-started/prerequisites.md) | Tools, AWS credentials, SSH keys |

## 🏗️ Architecture

| Document | Purpose |
|---|---|
| [Overview](architecture/overview.md) | High-level architecture (hybrid AWS + RPi) |
| [AWS Infrastructure](architecture/aws-infrastructure.md) | Terraform modules and AWS layout |
| [Kubernetes](architecture/kubernetes.md) | k3s cluster, Kustomize layout, ingress |
| [GitOps](architecture/gitops.md) | ArgoCD App-of-Apps with SOPS CMP |
| [Networking](architecture/networking.md) | Tailscale mesh and ts.net ingress |
| [Secrets Management](architecture/secrets-management.md) | SOPS + age workflow |

## ⚙️ Operations

| Document | Purpose |
|---|---|
| [Terraform](operations/terraform.md) | Apply workflow, state, modules |
| [Ansible](operations/ansible.md) | Roles, playbooks, inventory |
| [Testing](operations/testing.md) | Molecule, LocalStack, smoke tests, E2E |
| [SOPS Setup](operations/sops-setup.md) | Age key generation, encryption workflow |
| [Cost & Scheduling](operations/cost-and-scheduling.md) | EC2 cost breakdown and scheduler Lambda |
| [Resource Limits](operations/resource-limits.md) | Pod resource limits in the media namespace |

## 📦 Services

See the **[Services index](services/README.md)** for the full matrix of all 16 deployed apps with namespace, node, and ingress hostname.

## 🚨 Runbooks

| Runbook | Severity |
|---|---|
| [Control plane recovery](runbooks/control-plane-recovery.md) | 🔴 Critical |
| [Tailscale logged out](runbooks/tailscale-logged-out.md) | 🟡 Warning |
| [*** VPN failure](runbooks/***-vpn-failure.md) | 🟡 Warning |
| [Grafana dashboards broken](runbooks/grafana-dashboards.md) | 🟢 Info |

See [Runbooks index](runbooks/README.md).

## 🔧 Troubleshooting

Lower-severity issues that don't need an on-call response.

| Document | Purpose |
|---|---|
| [Torrent P2P debugging](troubleshooting/torrent-p2p.md) | Why peers won't connect through the VPN |

## 🔒 Security

| Document | Purpose |
|---|---|
| [Overview](security/overview.md) | Current security posture |
| [Audit history](security/audit-history.md) | Chronological record of audits |
| [Network policies](security/network-policies.md) | NET_ADMIN usage and NetworkPolicy design |
| [Fixes backlog](security/fixes-backlog.md) | Open security action items |
| [Latest review (2026-01-28)](reviews/2026-01-28-***-security.md) | *** security review |

## 🤝 Contributing

| Document | Purpose |
|---|---|
| [Project CONTRIBUTING](../CONTRIBUTING.md) | Workflow, PR process, code review |
| [Conventions](CONVENTIONS.md) | Naming, versioning, doc rules |
| [Doc style guide](contributing/doc-style.md) | Templates for runbooks, services, stubs |
| [Ansible roles](contributing/ansible-roles.md) | How to scaffold and test a new role |
| [Role template checklist](contributing/role-template.md) | What to fill in from `ansible/roles/.template/` |

## 📚 Reference

| Document | Purpose |
|---|---|
| [Makefile targets](reference/makefile-targets.md) | Every `make` target with one-line purpose |
| [Tailnet services](reference/tailnet-services.md) | Every `*.tail57bf10.ts.net` hostname |
| [Glossary](reference/glossary.md) | Project-specific terms |

## 📅 Plans & Reviews

| Section | Contents |
|---|---|
| [Plans](plans/README.md) | Forward-looking, time-boxed initiatives |
| [Reviews](reviews/) | Date-prefixed audit and review artifacts |

## 📁 Other directories

- [`analysis/`](analysis/) — one-off analyses still relevant to today's stack
- [`archive/`](archive/) — unmaintained content; excluded from CI link-checking. See [archive policy](archive/README.md).
