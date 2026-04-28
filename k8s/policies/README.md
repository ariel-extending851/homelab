# OPA Policies

> **Status:** Active
> **Owner:** @ariel-extending851

Policies in this directory are enforced by `conftest` against rendered K8s manifests as a blocking CI gate (`make validate-k8s-policies-critical`).

## Policies

| File | Enforces |
|---|---|
| `health_probes.rego` | Every container in Deployment/DaemonSet must declare a `readinessProbe`. |
| `rbac_safety.rego` | ClusterRoles must not use wildcard verbs/resources. Allowlist exempts system operators (see below). |
| `resource_limits.rego` | Every container declares both `requests` and `limits` for CPU and memory. |
| `security_context.rego` | Every container sets `securityContext.allowPrivilegeEscalation: false`. |

---

## Wildcard RBAC Allowlist

`rbac_safety.rego` blocks wildcard `verbs`/`resources` in ClusterRoles by default. The allowlist below documents specific ClusterRoles where wildcards are accepted because the operator's function genuinely requires broad access.

| ClusterRole | Justification | Added | Reviewer |
|---|---|---|---|
| `velero` | Cluster backup/DR. Velero must back up and restore *any* resource type — including CRDs introduced in the future. Enumerating resources risks silent backup gaps when new CRDs are added. | 2026-04-27 | @ariel-extending851 |
| `argocd-application-controller` | GitOps reconciliation. The controller applies any K8s manifest in the repo, including arbitrary CRDs. Enumerating would force a policy update for every new app type. | 2026-04-27 | @ariel-extending851 (preventive — ArgoCD ClusterRoles are not yet in this repo's manifests) |
| `argocd-server` | GitOps API/UI. Reads+writes app state across the cluster on behalf of users. | 2026-04-27 | @ariel-extending851 (preventive) |

### Adding to the allowlist

1. Open a PR that:
   - Adds the ClusterRole name to `wildcard_allowed_clusterroles` in `rbac_safety.rego`.
   - Adds a row to the table above with **justification**, **date**, and **reviewer**.
2. The justification must answer: *"Why does enumeration not work here?"* (e.g., the operator must handle arbitrary CRDs at runtime).
3. App namespaces (`adguard`, `golink`, `prometheus`, etc.) **never** belong on this list — they have well-defined permission boundaries.

### Periodic review

The allowlist should be reviewed when:
- A listed ClusterRole is removed from the cluster (delete the row).
- Upstream changes (e.g., new ArgoCD chart) reduce required permissions (re-evaluate).
- Annually, regardless: confirm each justification still holds.

---

## Running locally

```bash
make validate-k8s-policies-critical    # enforces all 4 policies, blocking
make validate-k8s-policies             # alias, same effect
```

Conftest runs against `kustomize build k8s/apps` output piped through a SOPS filter — encrypted resources are skipped.
