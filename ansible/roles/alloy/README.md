# ansible/roles/alloy — LEGACY (edge installation deprecated 2026-05-29)

> **Do not run this role against the Pi nodes.**

## Status

The original PR #114 installed Grafana Alloy as a native systemd service on
both Raspberry Pis using this role. Real-world operation revealed that Alloy
edge contended with Jellyfin transcoding on rasp-pi-04 — `discovery.kubernetes`
chatter to the apiserver (which is the k3s-server process on the same node)
plus shared SD-card I/O degraded streaming measurably.

The edge tier was pivoted on **2026-05-29** to **Promtail** via Kustomize at
[`../../../k8s/apps/promtail/`](../../../k8s/apps/promtail/). The Pi-only
overlay at [`../../../k8s/apps/envs/pi-only/kustomization.yaml`](../../../k8s/apps/envs/pi-only/kustomization.yaml)
now references that DaemonSet instead of this role.

## Why this role still exists

- **Audit / rollback:** if a future Alloy release fixes the discovery
  pressure (e.g. a static-config mode), this role is the starting point.
- **Cloud tier reference:** the templates here document the full eBPF
  config used by [`../../../k8s/apps/alloy/`](../../../k8s/apps/alloy/) on
  the EC2 worker (where the contention does not apply). Keep them in sync
  if the cloud Alloy config evolves.
- **Portfolio archaeology:** the design decisions captured in
  [`../../../docs/architecture/observability-alloy-ebpf.md`](../../../docs/architecture/observability-alloy-ebpf.md)
  reference these files; deleting them would orphan the ADR.

## Hard guard

The `alloy_native` group in [`../../inventory/production.yml`](../../inventory/production.yml)
is commented out. Running `ansible-playbook -i inventory/production.yml
playbooks/deploy-alloy.yml` against an empty group is a no-op. The molecule
scenarios under `molecule/` still pass — they exercise the role's logic
without a live target.

If you intentionally want to revive Alloy edge after the upstream fix, the
revival procedure is:

1. Read the post-mortem section in
   [`../../../docs/architecture/observability-alloy-ebpf.md`](../../../docs/architecture/observability-alloy-ebpf.md)
   (§ Edge tier revision 2026-05-29).
2. Confirm the upstream Alloy release notes claim the apiserver-chatter fix.
3. Reactivate `alloy_native` in `production.yml`.
4. Remove `promtail` from `k8s/apps/envs/pi-only/kustomization.yaml`
   *in the same commit* — running Alloy + Promtail simultaneously would
   double-ingest into Grafana Cloud Loki.
5. Re-apply, then validate the original Jellyfin-streaming workload.
