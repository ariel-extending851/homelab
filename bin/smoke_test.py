#!/usr/bin/env python3
"""Post-deploy smoke test — verifies cluster health after make deploy.

Port of bin/smoke-test.sh. Preserves identical checks, messages, and
exit codes (0 = all pass, 2 = minor app issues, 1 = critical failures).

Usage:
  KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml python3 bin/smoke_test.py
"""

import json
import os
import subprocess
import sys
from typing import NamedTuple

# Each (deployment, namespace) pair below tracks where the manifest actually
# lives in `k8s/apps/<app>/namespace.yaml`. Earlier versions assumed a shared
# `monitoring` namespace, but the homelab manifests put each observability
# component in its own namespace (see gotcha #11 in
# docs/runbooks/staging-deploy-2026-05-postmortem.md).
APPS = [
    ("adguard", "adguard"),
    ("blackbox", "blackbox"),
    ("golink", "golink"),
    ("grafana", "grafana"),
    ("kube-state-metrics", "kube-state-metrics"),
    ("loki", "loki"),
    ("node-exporter", "node-exporter"),
    ("otel-collector", "otel-collector"),
    ("prometheus", "prometheus"),
]

REQUIRED_NAMESPACES = ["argocd", "prometheus", "grafana", "loki", "adguard"]
POD_FAILURE_STATES = {
    "CrashLoopBackOff",
    "OOMKilled",
    "ImagePullBackOff",
    "ErrImagePull",
    "Error",
}


# ── parsing helpers (pure functions — contract-testable) ────────────────────


class AppStatus(NamedTuple):
    name: str
    sync_status: str
    health_status: str


class PodRow(NamedTuple):
    namespace: str
    name: str
    status: str


class PvcRow(NamedTuple):
    namespace: str
    name: str
    status: str
    volume: str


class StsRow(NamedTuple):
    namespace: str
    name: str
    ready: int
    desired: int


def parse_argocd_apps(stdout):
    """Parse `kubectl get applications -n argocd -o json` into a list of AppStatus.

    Returns [] if stdout is empty, JSON-invalid, or has no items.
    """
    if not (stdout or "").strip():
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    return [
        AppStatus(
            name=i["metadata"]["name"],
            sync_status=i.get("status", {}).get("sync", {}).get("status", ""),
            health_status=i.get("status", {}).get("health", {}).get("status", ""),
        )
        for i in data.get("items", [])
    ]


def parse_pod_status_lines(stdout):
    """Parse `kubectl get pods -A --no-headers`.

    Columns matched: NAMESPACE NAME READY STATUS ... → (ns, name, parts[3]=status).
    Lines with <4 columns are skipped (malformed).
    """
    rows = []
    for line in (stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 4:
            rows.append(PodRow(namespace=parts[0], name=parts[1], status=parts[3]))
    return rows


def parse_pvc_rows(stdout):
    """Parse `kubectl get pvc -A --no-headers`.

    Columns: NAMESPACE NAME STATUS VOLUME CAPACITY ACCESS STORAGECLASS AGE.
    Skips lines with <4 columns (malformed) and blank lines.
    """
    rows = []
    for line in (stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 4:
            rows.append(
                PvcRow(
                    namespace=parts[0],
                    name=parts[1],
                    status=parts[2],
                    volume=parts[3],
                )
            )
    return rows


def parse_statefulset_rows(stdout):
    """Parse `kubectl get statefulset -A --no-headers`.

    Columns: NAMESPACE NAME READY AGE, where READY is "current/desired" (e.g. "1/1").
    Skips lines with <3 columns or an unparseable READY field.
    """
    rows = []
    for line in (stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 3 or "/" not in parts[2]:
            continue
        ready_s, _, desired_s = parts[2].partition("/")
        try:
            ready, desired = int(ready_s), int(desired_s)
        except ValueError:
            continue
        rows.append(
            StsRow(namespace=parts[0], name=parts[1], ready=ready, desired=desired)
        )
    return rows


def parse_ready_replicas(stdout):
    """Parse a kubectl jsonpath integer output; returns 0 on blank/parse-error."""
    try:
        return int((stdout or "0").strip() or "0")
    except ValueError:
        return 0


class SmokeTest:
    def __init__(self, kubeconfig=None, argocd_ns="argocd"):
        self.kubeconfig = kubeconfig or "/tmp/k3s-homelab-kubeconfig.yaml"
        self.argocd_ns = argocd_ns
        self.failed = 0
        self.apps_failed = 0

    def pass_(self, msg):
        print(f"  ✓ {msg}")

    def fail(self, msg):
        print(f"  ✗ {msg}")
        self.failed += 1

    def kubectl(self, args, timeout=None):
        env = os.environ.copy()
        env["KUBECONFIG"] = self.kubeconfig
        cmd = ["kubectl", *args]
        if timeout is not None:
            cmd = ["kubectl", f"--request-timeout={timeout}s", *args]
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    # ── 1. Cluster reachability ──────────────────────────────────────────────

    def check_cluster_reachable(self):
        print("▶ Cluster connectivity")
        result = self.kubectl(["cluster-info"], timeout=10)
        if result.returncode == 0:
            self.pass_("API server reachable")
            return True
        self.fail(f"API server unreachable — check KUBECONFIG={self.kubeconfig}")
        print("   Cannot continue without API access.")
        return False

    # ── 2. ArgoCD apps ───────────────────────────────────────────────────────

    def check_argocd_apps(self):
        print("▶ ArgoCD sync status")
        result = self.kubectl(
            ["get", "applications", "-n", self.argocd_ns, "-o", "json"]
        )
        if result.returncode != 0:
            self.fail(f"No ArgoCD applications found (namespace: {self.argocd_ns})")
            return
        apps = parse_argocd_apps(result.stdout)
        if not apps:
            self.fail(f"No ArgoCD applications found (namespace: {self.argocd_ns})")
            return

        not_synced = [a.name for a in apps if a.sync_status != "Synced"]
        not_healthy = [a.name for a in apps if a.health_status != "Healthy"]

        if not not_synced:
            self.pass_("All ArgoCD apps are Synced")
        else:
            self.fail(f"Not Synced: {', '.join(not_synced)}")

        if not not_healthy:
            self.pass_("All ArgoCD apps are Healthy")
        else:
            self.fail(f"Not Healthy: {', '.join(not_healthy)}")

    # ── 3. Pod health ────────────────────────────────────────────────────────

    def check_pod_health(self):
        print("▶ Pod health (all namespaces)")
        result = self.kubectl(["get", "pods", "-A", "--no-headers"])
        failing = [
            f"    {p.namespace}/{p.name} ({p.status})"
            for p in parse_pod_status_lines(result.stdout)
            if p.status in POD_FAILURE_STATES
        ]

        if not failing:
            self.pass_("No pods in failure state")
        else:
            self.fail("Pods in failure state:")
            for line in failing:
                print(line)

    # ── 4. Namespace presence ────────────────────────────────────────────────

    def check_namespaces(self):
        print("▶ Namespace presence")
        for ns in REQUIRED_NAMESPACES:
            result = self.kubectl(["get", "namespace", ns])
            if result.returncode == 0:
                self.pass_(f"Namespace '{ns}' exists")
            else:
                self.fail(f"Namespace '{ns}' missing")

    # ── 5. ArgoCD repo-server ────────────────────────────────────────────────

    def check_argocd_repo_server(self):
        print("▶ ArgoCD repo-server pod")
        result = self.kubectl(
            [
                "get",
                "deployment",
                "argocd-repo-server",
                "-n",
                self.argocd_ns,
                "-o",
                "jsonpath={.status.readyReplicas}",
            ]
        )
        ready_n = parse_ready_replicas(result.stdout)

        if ready_n >= 1:
            self.pass_(f"argocd-repo-server has {ready_n} ready replica(s)")
        else:
            self.fail(
                "argocd-repo-server has no ready replicas " "(SOPS CMP may be broken)"
            )

    # ── 6. App deployments ───────────────────────────────────────────────────

    def check_app_deployments(self):
        print(f"▶ Application deployment health ({len(APPS)} apps)")
        for app, ns in APPS:
            ready = self._deployment_int(app, ns, "{.status.readyReplicas}")
            desired = self._deployment_int(app, ns, "{.spec.replicas}")
            if ready >= 1 and ready == desired:
                self.pass_(f"{app} ({ns}): {ready}/{desired} replicas ready")
            else:
                print(
                    f"  ✗ {app} ({ns}): {ready}/{desired} replicas "
                    f"(expected {desired})"
                )
                self.apps_failed += 1

    def _deployment_int(self, name, ns, jsonpath):
        result = self.kubectl(
            ["get", "deployment", name, "-n", ns, "-o", f"jsonpath={jsonpath}"]
        )
        return parse_ready_replicas(result.stdout)

    # ── 7. PVC validation ────────────────────────────────────────────────────

    def check_pvcs(self):
        print("▶ Persistent Volume Claims (PVCs)")
        result = self.kubectl(["get", "pvc", "-A", "--no-headers"])
        pvcs = parse_pvc_rows(result.stdout)
        unbound = [
            f"    {p.namespace}/{p.name} ({p.status}, volume={p.volume})"
            for p in pvcs
            if p.status != "Bound"
        ]

        if not unbound:
            self.pass_(f"All {len(pvcs)} PVCs are Bound")
        else:
            self.fail("PVCs not Bound:")
            for line in unbound:
                print(line)

    # ── 8. Observability stack ───────────────────────────────────────────────

    def check_observability(self):
        print("▶ Observability stack (Prometheus + Loki)")
        prom_ready = self._deployment_int(
            "prometheus", "prometheus", "{.status.readyReplicas}"
        )
        loki_ready = self._deployment_int("loki", "loki", "{.status.readyReplicas}")

        if prom_ready >= 1:
            self.pass_(f"Prometheus: {prom_ready} replica(s) ready")
        else:
            self.fail("Prometheus: no ready replicas")

        if loki_ready >= 1:
            self.pass_(f"Loki: {loki_ready} replica(s) ready")
        else:
            self.fail("Loki: no ready replicas")

    # ── 9. StatefulSets ──────────────────────────────────────────────────────

    def check_statefulsets(self):
        print("▶ StatefulSet replicas")
        result = self.kubectl(["get", "statefulset", "-A", "--no-headers"])
        sts = parse_statefulset_rows(result.stdout)
        mismatched = [
            f"    {s.namespace}/{s.name}: {s.ready}/{s.desired}"
            for s in sts
            if s.ready != s.desired
        ]

        if not mismatched:
            if sts:
                self.pass_(f"All {len(sts)} StatefulSets match desired replicas")
            else:
                self.pass_("No StatefulSets to validate")
        else:
            self.fail("StatefulSets replicas mismatch:")
            for line in mismatched:
                print(line)

    # ── Orchestrator ─────────────────────────────────────────────────────────

    def run(self):
        print(f"🔍 Post-deploy smoke tests (KUBECONFIG={self.kubeconfig})")
        print()

        if not self.check_cluster_reachable():
            return 1

        self.check_argocd_apps()
        self.check_pod_health()
        self.check_namespaces()
        self.check_argocd_repo_server()
        self.check_app_deployments()
        self.check_pvcs()
        self.check_observability()
        self.check_statefulsets()

        print()
        if self.failed == 0 and self.apps_failed == 0:
            print("✅ All smoke tests passed — cluster is production-ready.")
            return 0
        if self.failed == 0 and self.apps_failed < 3:
            print(
                f"⚠️  Minor issues ({self.apps_failed} app(s)) — "
                "investigate before release."
            )
            return 2
        print(
            f"❌ {self.failed} smoke test(s) FAILED "
            f"({self.apps_failed} app(s)) — ROLLBACK recommended."
        )
        return 1


def main():
    kubeconfig = os.environ.get("KUBECONFIG") or "/tmp/k3s-homelab-kubeconfig.yaml"
    argocd_ns = os.environ.get("ARGOCD_NAMESPACE", "argocd")
    return SmokeTest(kubeconfig=kubeconfig, argocd_ns=argocd_ns).run()


if __name__ == "__main__":
    sys.exit(main())
