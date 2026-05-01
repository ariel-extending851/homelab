# On-Call & Escalation

This is a **single-operator homelab**, so "on-call" is a process for one
person (the owner) plus a small set of fallbacks for when life gets in
the way. The point of writing it down is the same as on a real team:
when an incident hits, you don't want to be deciding what to do for the
first time.

## Who to wake up

| Layer | Primary | Fallback |
|---|---|---|
| Anything (default) | Repo owner (Ariel) | Spouse / cohabitant — knows where the runbooks live and that the cluster is the obvious culprit if Wi-Fi feels weird |
| AWS billing surprise | Repo owner | Trigger: `Infracost gate` failure or AWS Budget alert exceeding $20/day. Pause CI, then investigate. |
| Public-internet exposure | Repo owner | This means: "hostile traffic on a Tailscale node", "Cloudflare credentials exfiltrated", or similar. Burn keys first, ask questions later — see `docs/runbooks/sops-key-rotation.md`. |

There is **no on-call rotation**. If the owner is unreachable for >24h
and nothing in the table above matches, the cluster is probably fine to
leave alone — most failures self-heal via ArgoCD reconciliation +
Velero restore.

## How to know there's an incident

In rough order of how loudly each shouts:

1. **Velero restore drill failure** (monthly cron) → opens GitHub issue
   tagged `dr-drill, high-priority`. Email notification on the issue.
2. **Drift detection failure** (daily cron) → opens / updates rolling
   issue tagged `drift-detection, high-priority`.
3. **Deploy rollback fired** → CI workflow `rollback` job runs
   `terraform destroy` and opens an issue tagged `deployment, failure`.
4. **Prometheus alerts** → currently only visible in the Prometheus /
   Grafana UI (no Alertmanager wired yet — see
   `docs/runbooks/observability-availability.md`).
5. **Tailscale dropping you out** → see
   `docs/runbooks/tailscale-logged-out.md`.

Set up GitHub email notifications for those three issue labels and
you've covered the loud signals.

## Triage flow

When an issue opens:

1. **Read the latest runbook for that runbook label first.** They live
   in `docs/runbooks/`. Each one has a "verification" section showing
   the exact command to run.
2. **Don't restart the platform.** k3s self-heals; restarting nodes
   often hides the root cause. The exception: a stuck etcd / control
   plane — see `docs/runbooks/control-plane-recovery.md`.
3. **If unsure, do the safer thing.** This is a homelab — there is no
   SLA. A 12-hour window of data-only services being down is fine if it
   means you don't make the cluster worse at 02:00.
4. **Write down what you did.** A two-line addition to the relevant
   runbook is more valuable than fixing the same incident twice.

## Severity vocabulary

For consistency in commit messages / issue triage:

| Word | Means | Action |
|---|---|---|
| **High-priority** | Affects ability to deploy, audit, or recover | Drop other work; address within 24h |
| **Sev-cluster** | Cluster-wide outage | Drop work immediately |
| **Sev-data** | Data-loss risk (Velero, PVC, S3) | Drop work immediately |
| **Annoyance** | Cosmetic, dashboards, missing alerts | Backlog |

## When to call this process broken

If you find yourself writing a fifth one-off runbook for the same kind
of incident, that's a signal to either:
- Automate the recovery (add it to a playbook)
- Add a Prometheus alert that catches it pre-incident
- Reconsider whether the affected service is worth running here

The point of single-operator ops is to keep the cognitive load
sustainable. If the cluster is generating more incidents than you can
absorb without dread, scale **down** (delete the noisy app), not up.
