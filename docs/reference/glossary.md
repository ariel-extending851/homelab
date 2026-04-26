# Glossary

> **Status:** Active
> **Last reviewed:** 2026-04-23
> **Owner:** @ariel-extending851

Project-specific terms used across the repo and docs. Standard Kubernetes / Terraform / AWS terms aren't included.

---

## Naming & Conventions

**`hl-` prefix**
Mandatory prefix for all project resources (cloud, Kubernetes, Git). E.g., `hl-k3s-control-plane-01`, `hl-main-vpc`. Defined in [`../CONVENTIONS.md`](../CONVENTIONS.md). May be omitted for app-specific resources inside a dedicated namespace (e.g., `media`).

**kebab-case**
All resource and filename casing convention: lowercase, hyphen-separated. No `SHOUTING_CASE`, no `camelCase`, no `snake_case` for resources.

---

## Architecture

**App-of-Apps**
ArgoCD pattern where a single root Application (`homelab-apps-root`) watches a directory of child Application definitions. Lets ArgoCD self-manage by adding/removing child apps as the directory contents change. See [`../architecture/gitops.md`](../architecture/gitops.md).

**CMP plugin**
"Config Management Plugin" — a sidecar that ArgoCD's `argocd-repo-server` invokes during manifest generation. Used here to run SOPS decryption on encrypted Secret manifests. See [`../architecture/secrets-management.md#how-argocd-decrypts-at-sync`](../architecture/secrets-management.md#how-argocd-decrypts-at-sync).

**ProxyClass** (Tailscale)
A `tailscale.com/v1alpha1` CRD that configures the Tailscale operator's proxy pods. The repo defines `default` and `high-bandwidth` (used by Grafana). See [`../architecture/networking.md#proxy-classes`](../architecture/networking.md#proxy-classes).

**Sync wave**
ArgoCD annotation (`argoproj.io/sync-wave`) that orders resource creation within an Application. Lower waves go first.

**PostSync hook**

**Killswitch**

---

## Network

**Tailnet**
A Tailscale network (mesh of WireGuard peers). This project's tailnet is `tail57bf10.ts.net`. Every node + the operator laptop joins it.

**MagicDNS**
Tailscale feature that auto-resolves `<hostname>` to the tailnet IP of the device with that name. Enabled in the Tailscale admin console.

**ts.net**
Tailscale's parent domain for managed TLS certificates. Each tailnet gets a subdomain (`tail57bf10.ts.net` for ours).

**SSM Session Manager**
AWS service that gives you a shell on an EC2 instance via the IAM-authenticated AWS API — no SSH port required. Used as break-glass when Tailscale is down. See [`../runbooks/tailscale-logged-out.md`](../runbooks/tailscale-logged-out.md).

---

## Storage / Workload

**Hardlink workflow**

**Local PV**

**SOPS catch-all rule**
Last rule in [`.sops.yaml`](../../.sops.yaml) that matches any `*.sops.yaml` file and any field whose name contains `token`, `secret`, `password`, `key`, `api_key`, or `credential`. Protects ad-hoc encrypted files without per-file rules.

---

## Lifecycle / Cost

**Spot instance (persistent)**
EC2 instance bought at the spot price with `instance-interruption-behavior: terminate` + `spot_options.spot_instance_type: persistent`. AWS auto-replaces it after a spot interruption (~5 min). All this repo's EC2 instances are persistent spot.

**Scheduler Lambda**
Lambda function in `infra/aws/modules/scheduler` triggered by EventBridge cron (10:00 BRT start, 21:00 BRT stop). Calls `StartInstances` / `StopInstances` to keep the AWS pair on for ~11 hr/day. See [`../operations/cost-and-scheduling.md`](../operations/cost-and-scheduling.md).

**SSM transfer bucket**
Separate S3 bucket (`homelab-ssm-transfer-bucket`) used by Ansible's `community.aws.aws_ssm` connection plugin to relay stdin/stdout. **Critical:** must be different from the Terraform state bucket so compromised nodes can't read decrypted secrets.

---

## Testing

**Molecule**
Ansible role testing framework. Each role has `molecule/default/` with `molecule.yml`, `converge.yml`, `verify.yml`. CI rejects roles missing this. See [`../operations/testing.md#molecule`](../operations/testing.md#molecule).

**LocalStack**
Local mock of AWS APIs. Used to validate Terraform plans without spending money or needing AWS creds. Doesn't cover EC2 spot behavior, IAM enforcement, or k3s install (which need real AWS). See [`../operations/testing.md#localstack`](../operations/testing.md#localstack).

**Conftest / OPA / Rego**
Open Policy Agent's policy-as-code. The repo's policies (`k8s/policies/*.rego`) enforce: every Deployment has a readinessProbe, no wildcard RBAC, every container has CPU+mem limits, no privilege escalation. Run with `make validate-k8s-policies`.

**Smoke test**
Quick post-deploy HTTP probe of every app. `make smoke-test`. Exit codes: 0 pass, 2 minor, 1 fail.

**E2E test**

---

## Operator / On-call

**Runbook**
Reactive on-call reference. Severity-tagged, tested. Lives in [`../runbooks/`](../runbooks/). Distinct from a "troubleshooting guide" which is for slower-paced, lower-severity issues.

**Hub**
[`../README.md`](../README.md) — the single entry point that links into every other doc bucket. If you can't find something from there in two clicks, the hub or the target doc is broken.

**Stub**
A minimal in-tree README (e.g., in `k8s/apps/<app>/` or `infra/aws/`) that exists for GitHub folder-rendering context and points readers at the canonical doc under `docs/`. See template in [`../contributing/doc-style.md#in-tree-stub-template`](../contributing/doc-style.md#in-tree-stub-template).

---

## Related

- **Naming and casing rules:** [`../CONVENTIONS.md`](../CONVENTIONS.md)
- **Doc style guide (templates):** [`../contributing/doc-style.md`](../contributing/doc-style.md)
- **Architecture overview (the "where things live" view):** [`../architecture/overview.md`](../architecture/overview.md)
