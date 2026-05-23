# Alloy + eBPF Observability Pipeline

> **Status:** Active (introduced 2026-05-23)
> **Owner:** @ariel-extending851
> **Related:** [`../runbooks/alloy-troubleshooting.md`](../runbooks/alloy-troubleshooting.md), [`../security/audit-history.md`](../security/audit-history.md) (2026-05-23 entry), [`./overview.md`](./overview.md)

This page is the authoritative architecture document for the Grafana Alloy
unified observability agent — both the edge (Raspberry Pi, native systemd)
and the cloud (EC2, in-cluster DaemonSet) deployments. It is also the source
ADR used to derive the portfolio README at
[`./portfolio-observability-pipeline-README.md`](./portfolio-observability-pipeline-README.md).

---

## 1. Mandate

Replace the per-signal agent sprawl (Prometheus / Loki / OTel Collector
side-by-side on the same host) with a **single Grafana Alloy binary** that
collects host metrics, eBPF-derived application telemetry, and structured
logs, then **fans out** to three independent sinks:

1. **Grafana Cloud Mimir** — long-retention metrics (13 months on the free
   tier with cardinality discipline).
2. **Grafana Cloud Loki** — 14-day hot log window for live dashboarding.
3. **AWS S3 cold-storage bucket** — gzip-compressed OTLP-proto batches,
   tiered to Deep Archive at 90 days, retained 2 years (configurable).

The pipeline must operate inside two very different envelopes:

| Tier  | Hosts                       | RAM     | Kernel  | Constraint                         |
| ----- | --------------------------- | ------- | ------- | ---------------------------------- |
| Edge  | RPi 3 (k3s-agent)           | 1 GB    | ≥ 5.4   | Native systemd; Beyla optional     |
| Edge  | RPi 4 (k3s-agent)           | 8 GB    | ≥ 5.10  | Native systemd; full pipeline      |
| Cloud | EC2 t3.medium k3s-server    | 4 GB    | ≥ 6.1   | DaemonSet excluded (memory budget) |
| Cloud | EC2 t3.small k3s-agent      | 2–4 GB  | ≥ 6.1   | DaemonSet, IAM Instance Profile    |

---

## 2. Architecture (component graph)

```
   Edge tier (k3s-agent, native systemd)        Cloud tier (k3s-agent, k8s DaemonSet)
   ─────────────────────────────────────        ────────────────────────────────────
   ansible/roles/alloy/                          k8s/apps/alloy/
        │                                              │
   /usr/local/bin/alloy                          grafana/alloy:v1.5.1 (privileged)
        │                                              │
   ┌────┴─────────────────────────┐            ┌──────┴──────────────────────────┐
   │ prometheus.exporter.unix     │            │ prometheus.exporter.unix        │
   │ beyla.ebpf  (kernel ≥ 5.4)   │            │ beyla.ebpf  (kernel ≥ 5.4)      │
   │ discovery.docker             │            │ discovery.kubernetes            │
   │ loki.source.docker           │            │ loki.source.kubernetes          │
   │ loki.source.journal          │            │ loki.source.journal             │
   └──────────────┬───────────────┘            └─────────────────┬───────────────┘
                  │                                              │
              [WAL /var/lib/alloy/wal]                       [WAL emptyDir 4Gi]
                  │                                              │
                  └────────────── three-way fan-out ─────────────┘
                          │                  │                  │
                          ▼                  ▼                  ▼
                  Grafana Cloud      Grafana Cloud      otelcol.exporter.awss3
                  Mimir (metrics)    Loki (14d hot)     ──► hl-observability-cold-storage
                                                            │ gzip + minute partitions
                                                            │ Standard → IA @30d
                                                            │ → Deep Archive @90d
                                                            │ → expire @730d
```

The **EC2 Alloy** is the only sink with S3 write access (granted via the
inline IAM policy `hl-alloy-s3-export-*` on the existing `k3s_node` role
— see [`../../infra/aws/modules/compute/main.tf`](../../infra/aws/modules/compute/main.tf)).
The RPi Alloys fan out **only** to Grafana Cloud because the edge tier has
no AWS credentials path.

---

## 3. Decision drivers

1. **Single binary, single config language (River).** Pi 3 cannot afford
   three separate agent processes. Alloy collapses `prometheus`, `promtail`,
   and `otelcol` into one supervised systemd unit.
2. **Zero-instrumentation app telemetry.** Beyla attaches uprobes / tracepoints
   at the kernel level — no library injection, no sidecar — and emits
   RED metrics + service-graph spans for any HTTP/HTTPS/gRPC service whose
   port matches the discovery selector.
3. **Long-term retention without a self-hosted TSDB.** Grafana Cloud's free
   tier holds 10 k active series and 50 GiB logs for 14 days; S3 Deep
   Archive holds the same data at ~$1/TB/month past 90 days.
4. **Strict naming compliance.** The labelled telemetry must NEVER surface
   individual product names of the containerized workloads on the Pis. The
   approved taxonomy is `containerized_microservice`,
   `media_streaming_daemon`, `high_throughput_local_service`. Defensive
   relabel rules and a CI contract test enforce this at three layers.

---

## 4. Alternatives evaluated

| Alternative | Why not |
| ----------- | ------- |
| **Keep separate Prometheus + Loki + OTel pods** (status quo before this change) | Wastes RAM on the 1 GB Pi 3; in-cluster Loki requires a PVC that the LAN has no high-availability story for; OTel Collector + node-exporter + cAdvisor stack is 3× the supervisor overhead of one Alloy binary. |
| **Grafana Agent (Static / Flow legacy)** | Superseded by Alloy upstream; River replaces YAML-based Flow; no point starting on a deprecated artifact for a portfolio piece. |
| **Pure OpenTelemetry Collector everywhere** | Beyla integrates more cleanly with Alloy's River component graph than with the upstream OTel Collector receiver model. We use `otelcol.*` River components for the S3 sub-pipeline because they're the only path to `awss3` today, but the upstream OTel Collector alone is overkill. |
| **Cilium Hubble for eBPF data-plane visibility** | Evaluated for the cluster data plane and **deferred** — see [`../../ansible/playbooks/cilium-flip.yml`](../../ansible/playbooks/cilium-flip.yml) and the architecture overview note about the 2 GB control-plane ceiling. Replacing Flannel with Cilium during bootstrap risks an unrecoverable cluster mid-flip. Beyla operates entirely in user space against existing kernel hooks — no CNI swap, no kube-proxy disruption, runs on stock Raspberry Pi OS kernels. The future Cilium migration is independent of this work. |
| **Falco eBPF for application telemetry** | Falco is for security events, not RED metrics. We keep Falco (already deployed) for runtime threat detection and add Beyla for app-level performance telemetry. Different signal, different probe set, no overlap. |

---

## 5. Compliance — workload labeling taxonomy

Workloads on the Raspberry Pi nodes are labelled by **class only**. The
container's `homelab.io/class` annotation (Docker label on the edge,
pod annotation in the cluster) drives a `service_class` telemetry label.

| Allowed class value                | Meaning                                                                    |
| ---------------------------------- | -------------------------------------------------------------------------- |
| `containerized_microservice`       | Generic stateless service running in a container                           |
| `media_streaming_daemon`           | Workload whose primary I/O is bulk media or content streaming              |
| `high_throughput_local_service`    | LAN-facing data plane with sustained high request rate                     |

**Three layers of enforcement:**

1. **At source** — `discovery.relabel` rules promote the annotation,
   then `labeldrop` everything that could surface a product name
   (`__meta_kubernetes_pod_name`, `__meta_kubernetes_pod_container_name`,
   `__meta_docker_container_name`, `pod`, `container`).
2. **At sink** — `prometheus.relabel.cardinality_guard` and
   `loki.process.normalize`'s `stage.drop` block run a defensive regex
   against `service`, `job`, `container_name`, and drop any series whose
   labels accidentally leak a forbidden product name.
3. **At commit time** — the contract test at
   [`../../bin/tests/contracts/test_no_forbidden_workload_names.py`](../../bin/tests/contracts/test_no_forbidden_workload_names.py)
   scans `k8s/apps/alloy/`, `ansible/roles/alloy/`, and this very
   documentation, and fails CI if any forbidden product name appears
   outside an explicit drop-regex declaration.

This is the same belt-and-braces pattern as the existing OPA / Conftest +
Kyverno + image-allowlist supply-chain defense — three independent gates,
none of which is on its own load-bearing.

---

## 6. Two deployment modes

### Edge (Raspberry Pi) — native systemd

- Ansible role: [`../../ansible/roles/alloy/`](../../ansible/roles/alloy/)
- Playbook: [`../../ansible/playbooks/deploy-alloy.yml`](../../ansible/playbooks/deploy-alloy.yml)
- Inventory group: `alloy_native` (defined in `production.yml`)
- Why systemd, not DaemonSet: the per-pod overhead (kubelet bookkeeping,
  cgroup container, k8s liveness probes) is wasted on a 1 GB Pi 3 where
  the kernel and `k3s-agent` are already memory-tight. Native install
  costs ~40 MiB of RSS instead of the DaemonSet's ~110 MiB.
- Memory ceiling: `MemoryMax=300M` on Pi 3, `1G` on Pi 4 (systemd unit
  template).

### Cloud (EC2) — k8s DaemonSet, IAM Instance Profile

- Manifests: [`../../k8s/apps/alloy/`](../../k8s/apps/alloy/)
- Node selection: `homelab.io/tier: cloud` — pins to the EC2 worker only;
  the k3s-server is excluded so its 2 GB memory budget stays intact.
- S3 auth: implicit via IMDSv2 (hop_limit raised from 1 to 2 in the
  launch template so the pod network can reach `169.254.169.254`). No
  access keys anywhere in the manifest. IAM policy is write-only:
  `s3:PutObject`, `s3:AbortMultipartUpload`. No `GetObject`, no
  `DeleteObject` — cold reads happen out-of-band with a separate role.
- Privileged container required for Beyla CO-RE probe load; documented
  + Kyverno-exempted in [`../security/runtime-enforcement.md`](../security/runtime-enforcement.md).

---

## 7. Migration strategy — stage, don't replace

This change adds Alloy **alongside** the existing in-cluster Prometheus /
Loki / OTel Collector stack. A follow-up PR will retire the in-cluster
stack once Alloy has accumulated 14 days of stable scrapes (matches the
GC Loki retention so we lose no live history). The follow-up PR is
explicitly scoped — it deletes `k8s/apps/prometheus`, `k8s/apps/loki`,
`k8s/apps/otel-collector`, `k8s/apps/node-exporter`,
`k8s/apps/kube-state-metrics` after a final backup snapshot, and updates
the Grafana datasources to point at Grafana Cloud.

This staged approach respects the homelab's "How we work here" Phase 1 /
Phase 2 split (see `CLAUDE.md`): Phase 1 = it runs end-to-end alongside;
Phase 2 = idempotency + retry + observability + decommission docs.

---

## 8. Consequences

**Wins:**
- Single agent surface to debug, version-pin, and monitor.
- Zero-instrumentation app-level RED metrics on every service that opens a
  TCP socket — no code changes.
- S3 Deep Archive at ~$1/TB/month is one to two orders of magnitude
  cheaper than retaining the same data in Loki or in any self-hosted TSDB.
- Edge nodes survive Grafana Cloud outages via the per-node WAL.

**Costs / risks:**
- One privileged DaemonSet (Kyverno exception is scoped, audited).
- Grafana Cloud 10 k active-series cap requires constant cardinality
  discipline — `prometheus.relabel.cardinality_guard` is the throttle.
- IAM hop-limit bump from 1 to 2 (still the AWS-recommended ceiling for
  pod workloads).
- Grafana Cloud URL endpoints currently ship plaintext in the SOPS file
  (the existing `.sops.yaml` rule only encrypts `*Token` / `*Key` / etc.).
  Recorded as residual risk in `audit-history.md` (2026-05-23); a `sops`-
  managed extension of `.sops.yaml` is the planned remediation.

---

## 9. Rollback path

1. Remove `- ./alloy` from `k8s/apps/kustomization.yaml`. ArgoCD will
   prune the DaemonSet on next sync.
2. Disable the systemd service on the Pis: `ansible -i ... alloy_native
   -m systemd -a 'name=alloy state=stopped enabled=false'`.
3. The existing in-cluster Prometheus / Loki / OTel stack stays running
   the entire time (this is the whole point of the staged migration).
4. Terraform `module "observability"` can be removed last; the bucket
   itself has `force_destroy = false` and lifecycle expiration handles
   pruning if it's left in place.

---

## 10. References

- Grafana Alloy: <https://grafana.com/docs/alloy/>
- Beyla (eBPF auto-instrumentation): <https://grafana.com/docs/beyla/>
- OTel Collector `awss3` exporter: <https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/awss3exporter>
- Existing homelab observability: [`./overview.md`](./overview.md), [`../services/monitoring-stack.md`](../services/monitoring-stack.md) (if present)
- Cilium deferral context: [`../../ansible/playbooks/cilium-flip.yml`](../../ansible/playbooks/cilium-flip.yml), [`./networking.md`](./networking.md)
