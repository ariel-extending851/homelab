# Homelab Documentation Hub

Welcome to the central documentation for the Homelab project. This hub organizes all documentation into logical categories, from getting started to deep architectural dives.

## 🚀 Getting Started

If you are new to the project, start here.

| Document | Purpose |
| :--- | :--- |
| **[Project README](../../README.md)** | The main entry point with a high-level overview. |
| **[Quickstart Guide](../../QUICKSTART.md)** | 5-minute guide to get the entire stack running. |
| **[Full Deployment Guide](../../AWS-DEPLOYMENT.md)** | A comprehensive, step-by-step guide to deployment. |

## 🏗️ Architecture & Design

Understand the "why" behind the project's design.

| Document | Purpose |
| :--- | :--- |
| **[Main Architecture](architecture.md)** | High-level architectural principles and project vision. |
| **[Terraform Architecture](../../infra/aws/docs/ARCHITECTURE.md)**| Deep-dive into the AWS infrastructure design. |
| **[Secrets Management](secrets-management.md)** | Strategy for handling secrets with SOPS and age encryption. |
| **[Security Audit](security/SECURITY_AUDIT.md)** | Comprehensive security analysis and hardening plan. |
| **[Platform Engineering Roadmap](plans/PLATFORM_ENGINEERING_ROADMAP.md)**| The future vision for the homelab as a platform. |

## ⚙️ Core Components

Detailed documentation for each major technology.

| Document | Purpose |
| :--- | :--- |
| **[Terraform](../../infra/aws/README.md)** | Documentation for all AWS modules, variables, and outputs. |
| **[Ansible](../../ansible/README.md)** | In-depth guide to all roles, playbooks, and inventory. |
| **[Kubernetes (k8s)](../../k8s/apps/DEPLOYMENT.md)** | Overview of the application deployment strategy using Kustomize. |
| **[GitOps](../../k8s/gitops/README.md)** | Explanation of the ArgoCD App-of-Apps model used. |

## 📖 Runbooks & Operations

Guides for day-to-day operations and emergency procedures.

| Document | Purpose |
| :--- | :--- |
| **[Critical Recovery Plan](runbooks/CRITICAL-RECOVERY-PLAN.md)** | How to recover the control plane if it goes down. |
| **[Tailscale Logged Out Recovery](runbooks/ROOT-CAUSE-TAILSCALE-LOGGED-OUT.md)**| Steps to fix Tailscale when devices can't connect. |
| **[Checklists](checklists/)** | Various checklists for pull requests, post-merge validation, etc. |
| **[Incidents](incidents/)** | Post-mortems and analysis of past incidents. |

## 🔍 Troubleshooting

Solutions for common problems.

| Document | Purpose |
| :--- | :--- |
| **[VPN Fix Implementation Plan](troubleshooting/VPN_FIX_IMPLEMENTATION_PLAN.md)** | Guide to debugging and fixing the *** VPN sidecar. |
| **[Performance Optimization Summary](troubleshooting/PERFORMANCE_OPTIMIZATION_SUMMARY.md)** | Analysis and solutions for performance issues. |
| **[Grafana Dashboard Troubleshooting](troubleshooting/grafana-dashboard-troubleshooting.md)** | How to fix broken or misconfigured Grafana panels. |

This documentation hub provides a clear and organized way to navigate the project.
