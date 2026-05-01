# Multi-Repo Strategy

The homelab platform now spans two Git repositories:

| Repo | Visibility | Purpose |
|---|---|---|
| **`homelab`** (this repo) | Public | Platform: infra (Terraform/Ansible), GitOps base (ArgoCD bootstrap, observability stack, network/security), reusable runbooks, CI/CD. |
| **media-stack** | Private | Application-layer manifests for personal media services (Jellyfin, Sonarr, etc.) that we don't want in a public repo. |

The split was made in commit `885f1ad` to keep the public repo free of
service-specific manifests, secrets, and references that aren't useful
to outside readers and would expose home network topology.

## How the two are wired

ArgoCD watches **both** repositories and reconciles them in parallel:

1. **Primary repo (`homelab`)** — wired via `git_repo_url` /
   `git_repo_path` in `ansible/roles/argocd/defaults/main.yml`. Default
   path is `k8s/apps`. Public deploy key.

2. **Secondary repo (`media-stack`)** — opt-in via the
   `argocd_extra_*` variables in the same role. The values live in an
   SOPS-encrypted group_vars file so the private repo's URL itself
   doesn't leak through this plaintext file. Wiring landed in commit
   `893475a`.

Both repos are reconciled by the same ArgoCD instance, with separate
`Application` resources. Failures in one don't block the other.

## What lives where (decision rule)

| Belongs in `homelab` (public) | Belongs in media-stack (private) |
|---|---|
| Anything an outside reader could learn from | Anything that names a personal service / dataset / domain |
| Reusable Ansible roles, k8s policies, CI templates | App-specific Deployment / Ingress / PVC manifests |
| Backup machinery (Velero), observability stack | Service credentials (even SOPS-encrypted) |
| Architecture docs, runbooks for shared concerns | Service-specific runbooks (e.g., "rebuilding the Jellyfin metadata DB") |

When in doubt: would I be uncomfortable with this paragraph being on
GitHub trending? → private repo.

## Coordinating changes across both

There is no shared CI between the repos. Coordination is by convention:

- **Tool versions** — `.mise.toml` lives in this repo; the private repo
  uses `mise install --shim-dir` to pull from the same lockfile when it
  needs matching tooling. Bumping a tool here is a signal to the other
  repo's maintainer.
- **Ansible role contracts** — roles in this repo (`ansible/roles/`)
  have stable variable interfaces enforced by Molecule tests. Changing a
  role's input shape means both repos need to update their playbook
  invocations.
- **ArgoCD chart pins** — the ArgoCD version is pinned in the `argocd`
  role here. The private repo just consumes whatever ArgoCD this repo
  installs; bumps land here first.
- **Velero / backup scope** — Velero is configured in this repo. Its
  backup schedule includes the namespaces from both repos because
  Velero scopes by namespace, not by source repo. New namespaces
  declared in the private repo need a one-line update to the Velero
  Schedule resource here.

## Onboarding a new private app

1. Open the private repo, add the manifest under `k8s/apps/<your-app>/`.
2. If it needs a new namespace, add a one-liner to the Velero Schedule
   here so it's backed up.
3. Push. ArgoCD picks it up within ~3min sync interval.
4. Watch the observability gate (`bin/post_deploy_observability_gate.py`
   results in CI) for OOM / restart loops.

## When the split should be revisited

Reconsider the split if:

- The private repo grows enough infra-level concerns that it duplicates
  this one (move them back here).
- We add a third consumer (another cluster?) and need a real Helm chart
  index instead of two ad-hoc repos.
- The SOPS-encrypted secondary-repo variables stop being enough
  isolation — e.g., we need per-app deploy keys.
