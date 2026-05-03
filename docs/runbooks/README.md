# Runbooks

> **Status:** Active
> **Last reviewed:** 2026-05-01
> **Owner:** @ariel-extending851

Reactive on-call references. Each runbook is severity-tagged and tested.

| Runbook | Severity | Last Tested |
|---|---|---|
| [Control plane recovery](control-plane-recovery.md) | 🔴 Critical | 2026-02-17 |
| [SOPS age key rotation](sops-key-rotation.md) | 🔴 Critical (when emergency) | — (review annually) |
| [On-call & escalation](on-call.md) | 🟠 Process | — (process doc) |
| [Tailscale logged out](tailscale-logged-out.md) | 🟡 Warning | 2026-02-17 |
| [Trivy CVE exceptions](trivy-exceptions.md) | 🟡 Process | — (CI gate workflow) |
| [GitHub Environments setup](github-environments.md) | 🟡 Setup | — (one-time) |
| [Observability stack — single-replica trade-off](observability-availability.md) | 🟢 Info | — (design rationale) |
| [Grafana dashboards broken](grafana-dashboards.md) | 🟢 Info | 2026-01-23 |
| [Staging deploy postmortem 2026-05](staging-deploy-2026-05-postmortem.md) | 🟡 Setup | 2026-05-03 |

Template for new runbooks: [`docs/contributing/doc-style.md`](../contributing/doc-style.md#runbook-template).

For lower-severity, slower-paced issues see [`docs/troubleshooting/`](../troubleshooting/).
