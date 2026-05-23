# Alloy Troubleshooting

> **Status:** Active (introduced 2026-05-23)
> **Owner:** @ariel-extending851
> **Pager scope:** Observability availability (non-critical)
> **Architecture:** [`../architecture/observability-alloy-ebpf.md`](../architecture/observability-alloy-ebpf.md)

Symptom-driven recovery guide for the Grafana Alloy agent on both deployment
modes (edge systemd + cloud DaemonSet). When in doubt, check the dashboard
first (Grafana Cloud → Explore → `up{cluster="homelab"}`) before changing
anything on the nodes.

---

## Diagnostic quick-checks

```bash
# Edge — both Pis
ansible -i ansible/inventory/production.yml alloy_native \
  -m shell -a 'systemctl status alloy --no-pager; \
               journalctl -u alloy -n 100 --no-pager'

# Cloud — DaemonSet
kubectl -n alloy get ds,pods,svc,ingress
kubectl -n alloy logs -l app=alloy --tail=200

# Self-readiness on either tier
curl -sf http://localhost:12345/-/ready    # native systemd
kubectl -n alloy port-forward svc/alloy 12345:12345
curl -sf http://localhost:12345/-/ready    # cluster mode

# Is data actually arriving?
#   Grafana Cloud → Explore → up{cluster="homelab"}    (metrics)
#   Grafana Cloud → Explore → {cluster="homelab"} |= ""  (logs)
#   aws s3 ls s3://hl-observability-cold-storage-XXXX/alloy/  (cold archive)
```

---

## Symptom 1 — Service fails to start on Raspberry Pi

**Diagnostic:**
```bash
ansible -i .../production.yml rasp-pi-03 \
  -m shell -a 'journalctl -u alloy -n 50 --no-pager'
```

**Common causes:**

| Log line                                                    | Cause                              | Fix |
| ----------------------------------------------------------- | ---------------------------------- | --- |
| `Kernel X.Y.Z is below Beyla minimum 5.4`                   | Stock Pi OS kernel too old         | `apt full-upgrade && reboot`, or set `alloy_enable_beyla: false` per-host. |
| `Architecture armv7l is not supported`                      | 32-bit Pi OS image                 | Reflash to 64-bit Raspberry Pi OS Bookworm arm64. |
| `Only X MiB free; Alloy preflight requires >= 128 MiB`      | Pi 3 over-committed                | See [`./rpi-oom-mitigation.md`](./rpi-oom-mitigation.md). |
| `permission denied: /sys/kernel/debug/...`                  | Capabilities not effective         | Confirm `AmbientCapabilities=CAP_BPF CAP_PERFMON ...` survived a `daemon-reload`. |
| `MemoryMax: process killed by oom-killer`                   | `MemoryMax=300M` too tight on Pi 3 | Either raise to 400M in host_vars, or disable Beyla. |

---

## Symptom 2 — Beyla attaches but reports no probes

**Diagnostic:**
```bash
# Live debug UI (only reachable on the tailnet)
curl https://alloy.tail57bf10.ts.net/debug/livedebugging
# Or:
kubectl -n alloy logs -l app=alloy | grep -i beyla
```

**Common causes:**
- **Missing BTF on the host kernel.** Probe goes through but CO-RE can't
  rewrite offsets. Logs include `BTF not available`. Fix: install
  `linux-headers-$(uname -r)` (Debian / Ubuntu) or accept the kprobes
  fallback (degraded but functional).
- **Pod is not `privileged: true` + `hostPID: true`.** Beyla needs to read
  `/proc/<pid>/maps` across PID namespaces. Confirm both flags are set;
  Kyverno PolicyException at `k8s/apps/alloy/policy-exception.yaml` is
  what lets this through admission.
- **No services match the discovery selector.** `discovery.services` is
  port-range based — confirm the workload exposes a TCP port and isn't
  using a UNIX socket only.

---

## Symptom 3 — Grafana Cloud auth fails (401 / 403)

**Diagnostic:** look for `prometheus_remote_write_failed_total` rising or
`401` in the Alloy logs.

**Procedure (token rotation):**
1. Mint a new token in the Grafana Cloud admin: <https://grafana.com/orgs/> → MyAccount → Cloud Access Policies → "Add policy" → scopes `metrics:write` + `logs:write`. Copy the `glc_` token.
2. Decrypt the relevant SOPS file:
   - Edge: `sops ansible/group_vars/alloy_native.sops.yaml`
   - Cloud: `sops k8s/apps/alloy/secret.yaml`
3. Replace `GRAFANA_CLOUD_TOKEN`. Save & exit (SOPS re-encrypts on save).
4. Commit and let ArgoCD / Ansible apply.
5. Roll the agents:
   - Edge: `ansible -i ... alloy_native -m systemd -a 'name=alloy state=restarted'`
   - Cloud: `kubectl -n alloy rollout restart ds/alloy`
6. Revoke the old token in the Grafana Cloud admin.

**Common causes:**
- Token was scoped `metrics:read` instead of `metrics:write`.
- The `GRAFANA_CLOUD_USER` (instance ID) doesn't match the tenant the
  token was minted in.
- The URL has the wrong region (`prometheus-prod-13-...` vs `-06-...`).
  Verify in the Grafana Cloud "Connections" → Prometheus → "URL" field.

---

## Symptom 4 — S3 backpressure / `otelcol_exporter_queue_size` rising

**Diagnostic:**
```promql
otelcol_exporter_queue_size{cluster="homelab"} > 4000
rate(otelcol_exporter_send_failed_log_records_total[5m]) > 0
```

**Common causes:**
- **IMDSv2 hop limit not raised.** Pod gets `403 Forbidden` from IMDSv2.
  Confirm `terraform -chdir=infra/aws state show module.k3s_cluster.aws_launch_template.k3s_agent | grep hop_limit` shows `2`. If it shows `1`, run `terraform apply` to pick up the change in `infra/aws/modules/compute/main.tf` (this was the launch-template change introduced alongside the observability module).
- **IAM policy missing.** Confirm:
  ```bash
  aws iam list-role-policies --role-name $(aws iam list-roles --query \
    'Roles[?starts_with(RoleName, `hl-k3s-node-`)].RoleName' --output text)
  ```
  expects `hl-alloy-s3-export-*` in the output.
- **Bucket policy rejects PUT.** Bucket policy denies `s3:PutObject` when
  `x-amz-server-side-encryption != AES256`. Alloy sets this header
  automatically; if you see this denial, it usually means a manual `aws
  s3 cp` test was run without `--sse AES256`.
- **Region mismatch.** `AWS_REGION` env in the pod doesn't match the
  bucket region. The S3 endpoint resolves locally but the PutObject is
  cross-region and may fail with redirect.

---

## Symptom 5 — Grafana Cloud 429 (ingest quota exceeded)

**Diagnostic:**
```promql
rate(prometheus_remote_storage_failed_samples_total[5m]) > 0
# Logs: "received 429 too many requests"
```

**Mitigation:**
1. Identify the offending series:
   ```promql
   topk(20, count by (__name__)({}))
   ```
2. Add a drop rule to `prometheus.relabel.cardinality_guard` in
   `config.alloy` (edge: template; cloud: ConfigMap). Common offenders:
   - `container_label_io_kubernetes_*` (drop by `labeldrop` regex).
   - cAdvisor's `id` / `name` labels (already dropped).
   - High-cardinality `route` labels from Beyla (use `attributes.select`
     to exclude noisy paths like `/metrics`).
3. Restart Alloy.

The on-disk WAL holds samples during a 429 storm; nothing is lost unless
the WAL itself overflows (8 h retention by default).

---

## Symptom 6 — Cardinality budget alarm

The home dashboard panel "Cluster series" should stay under 9,000 active
series for the Grafana Cloud free tier (10 k hard cap). Cross 9,000 and
the alert fires; cross 10 k and the previous symptom (429) kicks in.

Same mitigation as Symptom 5: identify, drop, restart.

---

## Symptom 7 — Journal cursor reset / log gap

**Diagnostic:** Alloy logs include `journal: failed to load cursor`.

**Common cause:** the systemd journal was rotated mid-restart and Alloy
started from `tail` instead of resuming. Logs from the rotation window
are lost. Mitigation: switch `loki.source.journal` to `path` mode (reads
the on-disk binary directly) instead of the live journal stream — pinned
as a follow-up, not a hot fix.

---

## Symptom 8 — DaemonSet pod blocked by Kyverno

**Diagnostic:**
```bash
kubectl -n alloy describe pod -l app=alloy | grep -i 'kyverno\|admission'
```

Expected: no admission denials because `k8s/apps/alloy/policy-exception.yaml`
exempts the namespace from `disallow-privileged-containers`,
`disallow-host-namespaces`, and `disallow-capabilities`.

If you see a denial: the PolicyException didn't sync. Check ArgoCD,
re-sync the `alloy` app manually, and confirm the PolicyException
exists (`kubectl get policyexception -n alloy`).

---

## Symptom 9 — `alloy fmt` validation fails during Ansible converge

The `template:` task uses `validate: "/usr/local/bin/alloy fmt --test %s"`.
If the binary is missing or wrong-arch, the rendered config is rolled
back. Inspect:

```bash
ansible -i ... alloy_native -m shell -a 'ls -l /usr/local/bin/alloy; /usr/local/bin/alloy --version'
```

Fix: re-run `--tags alloy` with `-vvv` and look at the install step for
the actual checksum-verification failure (Grafana's `SHA256SUMS` URL is
the source of truth; if upstream re-published a release the hash will
have changed).

---

## Escalation

- Pipeline still down after 30 minutes of the above → open an incident
  with the `sre` agent (`/incident`) and link this runbook in the ticket.
- Suspected data leak (workload product name appeared in a label) →
  immediately revert the offending commit, then verify the contract test
  at `bin/tests/test_no_forbidden_workload_names.py` did NOT
  flag the change (if it didn't, the test allowlist needs tightening).
- Token leak in plaintext logs → rotate (Symptom 3), then audit the
  affected log scrape range and consider purging the Grafana Cloud
  Loki window if the token appeared in a captured log line.
