# Single-AZ Trade-Off

The AWS portion of this homelab runs in **one Availability Zone** in
`us-east-1`. This document records why, what we lose, and what would
trigger reconsidering.

## Why single-AZ

| Cost factor | Single-AZ (today) | Multi-AZ |
|---|---|---|
| Inter-AZ data transfer | $0 — all traffic stays in one AZ | $0.01/GB each direction. With observability scrapes + ArgoCD diffs this adds ~$3-8/mo |
| EBS volumes | One volume per node | Either replicate across AZs (Longhorn / Rook, ~2x storage cost + operational burden) or accept that PVCs are AZ-bound |
| Spot interruption | One AZ pool — interruption → wait for capacity to come back | Multi-pool reduces interruption risk by ~30-50% |
| Operational complexity | Trivially flat: `data.aws_subnets.default` picks any subnet, instances land where capacity is | StatefulSets need topology spread constraints; PVCs need migration strategy |

For a personal homelab whose target SLO is "best-effort, 95%-ish
business hours availability", multi-AZ pays roughly $5-10/mo for HA we
don't actually consume. The decision is recorded here so future-me
doesn't relitigate it without thinking about the cost side.

## What we lose

- **AZ-wide outage** = full homelab outage. AWS publishes us-east-1 AZ
  outages a few times a year, typically resolved in <2h. We accept
  this.
- **Spot capacity** is per-AZ. If our single AZ runs out of t3.medium
  spot, the cluster sits in `Pending` until capacity returns. Mitigate
  by setting `spot_max_price` close to on-demand (so we keep the
  capacity even if price spikes).
- **PVC mobility** is non-existent. A pod with a PVC is pinned to its
  AZ. This is fine because we already have `replicas: 1` for everything
  with state — see
  [observability-availability.md](../runbooks/observability-availability.md).

## When to revisit

Move to multi-AZ if any of the following becomes true:

1. We start running services where >2h downtime causes real user impact
   (paying users, family-shared services they expect to "just work").
2. AWS spot capacity in our single AZ becomes routinely unavailable
   (>1 incident/week of pending pods).
3. The cluster grows past ~5 nodes — at that scale per-node failure
   blast radius is large enough that AZ failure isn't materially worse,
   so spreading is roughly free.
4. We're already paying for cross-AZ traffic for some other reason
   (e.g., RDS multi-AZ landed for compliance), making the marginal cost
   of multi-AZ EC2 effectively zero.

## How a multi-AZ migration would look (sketch)

For the day this hits:
- `infra/aws/modules/network`: stop using `data.aws_subnets.default`
  unfiltered; pin to ≥2 specific AZs.
- `infra/aws/modules/compute`: split server/agent into separate ASGs
  per-AZ, or use Karpenter for AZ-aware spot bin-packing.
- Storage: install Longhorn (replicates PVCs across nodes/AZs) or
  switch stateful workloads to RDS / EFS where appropriate.
- Observability: keep Prometheus single-replica (already documented
  trade-off) but pin its PVC to the AZ that holds Grafana, so loss of
  one AZ degrades observability gracefully rather than splitting it.

This is documented as **roughly 1-2 weeks of focused work**, not a
weekend. Don't start until the trigger conditions above are real.
