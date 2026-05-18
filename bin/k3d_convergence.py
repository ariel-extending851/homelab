"""k3d pre-deploy GitOps convergence harness — helpers + thin CLI.

Companion to `bin/tests/test_k3d_gitops_convergence.py`. Spins up a k3d
cluster, installs ArgoCD, applies the homelab app-of-apps, and exposes
inspection helpers for the test to query convergence state.

Why k3d not kind: k3d ships k3s, the same distro the prod cluster runs.
Sync-wave timing and CRD readiness behave subtly differently between k3s
and upstream kubeadm — testing on k3s makes the pre-deploy gate faithful.

SOPS / sealed-secrets: in CI we don't have the prod AGE key, so apps
that need sops-decrypted Secrets will fail to sync. The convergence test
distinguishes ComparisonError/SyncError (which we always flag) from a
plain `Missing` health (which is acceptable and surfaced as a warning,
controllable via the env var `IGNORE_MISSING_SECRET_APPS=1`).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
ARGOCD_VERSION = os.environ.get("ARGOCD_VERSION", "v3.0.6")
ARGOCD_INSTALL_URL = (
    f"https://raw.githubusercontent.com/argoproj/argo-cd/"
    f"{ARGOCD_VERSION}/manifests/install.yaml"
)
ROOT_APP_MANIFEST = REPO_ROOT / "k8s" / "gitops" / "apps-root.yaml"


# ── shell wrappers ───────────────────────────────────────────────────────


def _run(
    *cmd: str, capture: bool = False, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a subprocess; fail loudly on non-zero unless check=False."""
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True, check=check)
    return subprocess.run(cmd, text=True, check=check)


def _kubectl_json(*args: str) -> dict:
    res = _run("kubectl", *args, "-o", "json", capture=True, check=False)
    if res.returncode != 0:
        return {}
    try:
        return json.loads(res.stdout)
    except json.JSONDecodeError:
        return {}


# ── lifecycle ────────────────────────────────────────────────────────────


def create_k3d_cluster(name: str) -> None:
    """Spin up a fresh single-node k3d cluster.

    Idempotent: deletes any cluster with the same name first so re-runs in
    CI never inherit stale state.
    """
    _run("k3d", "cluster", "delete", name, check=False)
    _run(
        "k3d",
        "cluster",
        "create",
        name,
        "--agents",
        "0",
        "--wait",
        "--timeout",
        "120s",
    )


def delete_k3d_cluster(name: str) -> None:
    """Best-effort teardown — never raise; run from finalizers/finally blocks."""
    _run("k3d", "cluster", "delete", name, check=False)


def wait_for_cluster_ready(timeout: int) -> None:
    """Poll until every node has Ready=True."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        nodes = _kubectl_json("get", "nodes")
        items = nodes.get("items") or []
        if items and all(_node_ready(n) for n in items):
            return
        time.sleep(2.0)
    raise AssertionError(f"k3d cluster did not become Ready in {timeout}s")


def _node_ready(node: dict) -> bool:
    for c in node.get("status", {}).get("conditions", []):
        if c.get("type") == "Ready":
            return c.get("status") == "True"
    return False


def apply_argocd() -> None:
    """Install ArgoCD into the `argocd` namespace from the upstream manifest.

    We pin the version via `ARGOCD_VERSION` (env override) so a newly-released
    ArgoCD with breaking schema changes can't silently break this gate.
    """
    _run("kubectl", "create", "namespace", "argocd", check=False)
    _run("kubectl", "-n", "argocd", "apply", "-f", ARGOCD_INSTALL_URL)


def _workload_fully_ready(kind: str, name: str) -> bool:
    """True when the named Deployment/StatefulSet has readyReplicas == replicas.

    Treats absent or zero spec.replicas as not-yet-scheduled (False).
    """
    obj = _kubectl_json("-n", "argocd", "get", kind, name)
    if not obj:
        return False
    spec = obj.get("spec", {})
    status = obj.get("status", {})
    desired = spec.get("replicas")
    return bool(desired) and status.get("readyReplicas") == desired


def wait_for_argocd_server_ready(timeout: int) -> None:
    """Block until ArgoCD's data-plane workloads are all Ready.

    Waits for *every* component the comparison loop touches:
      - argocd-server (UI/API)               — Deployment
      - argocd-repo-server (manifest gen)    — Deployment
      - argocd-application-controller        — StatefulSet

    Earlier versions only waited for argocd-server, which let the test
    proceed to apply the root app while the controller was still racing
    against a not-yet-ready repo-server. The controller would record a
    transient `ComparisonError: dial … :8081: connection refused`, and
    `wait_for_root_app_evaluated` (which treats any ComparisonError as
    fatal) would fail before the repo-server finished pulling its image.
    """
    deadline = time.monotonic() + timeout
    workloads = [
        ("deployment", "argocd-server"),
        ("deployment", "argocd-repo-server"),
        ("statefulset", "argocd-application-controller"),
    ]
    while time.monotonic() < deadline:
        if all(_workload_fully_ready(kind, name) for kind, name in workloads):
            return
        time.sleep(3.0)
    not_ready = [
        f"{kind}/{name}"
        for kind, name in workloads
        if not _workload_fully_ready(kind, name)
    ]
    raise AssertionError(
        f"ArgoCD workloads not Ready in {timeout}s: {', '.join(not_ready)}"
    )


def apply_root_app(
    repo_url_override: Optional[str] = None,
    target_revision_override: Optional[str] = None,
) -> None:
    """Apply the homelab app-of-apps with CI-safe rewrites.

    The shipped manifest at `k8s/gitops/apps-root.yaml` uses an SSH
    repoURL (`git@github.com:...`). The k3d cluster's argocd-repo-server
    has no SSH credentials, so applying it as-is produces an immediate
    ComparisonError on the root and times out the convergence wait.

    Rewrites in priority order:
      1. Explicit overrides (CI passes these via env).
      2. `K3D_REPO_URL_OVERRIDE` / `K3D_TARGET_REVISION_OVERRIDE` env.
      3. Default: SSH → HTTPS rewrite + targetRevision pinned to HEAD
         (the actual PR commit, not whatever the manifest hardcodes).

    A public-repo HTTPS fetch is rate-limited but works without creds.
    For private repos, set `K3D_REPO_URL_OVERRIDE` to a fork or mirror,
    or skip Test #3 in CI by removing the workflow trigger.
    """
    if not ROOT_APP_MANIFEST.exists():
        raise FileNotFoundError(f"root app manifest not found at {ROOT_APP_MANIFEST}")
    raw = ROOT_APP_MANIFEST.read_text()

    repo_url = repo_url_override or os.environ.get("K3D_REPO_URL_OVERRIDE")
    if not repo_url:
        repo_url = _ssh_to_https(_extract_field(raw, "repoURL"))
    target_rev = target_revision_override or os.environ.get(
        "K3D_TARGET_REVISION_OVERRIDE"
    )
    if not target_rev:
        target_rev = _current_git_sha() or _extract_field(raw, "targetRevision")

    rewritten = _rewrite_yaml_field(raw, "repoURL", repo_url)
    rewritten = _rewrite_yaml_field(rewritten, "targetRevision", target_rev)
    rewritten = _strip_sops_kustomize_plugin(rewritten)

    subprocess.run(
        ["kubectl", "apply", "-f", "-"], input=rewritten, text=True, check=True
    )


def _strip_sops_kustomize_plugin(yaml_text: str) -> str:
    """Remove the `plugin: { name: sops-kustomize }` block from a rewritten root.

    The shipped apps-root.yaml sets `spec.source.plugin.name: sops-kustomize`
    so ArgoCD invokes the CMP that walks the repo, decrypts SOPS-encrypted
    YAML, and runs kustomize build. In this k3d test environment we install
    vanilla upstream ArgoCD (apply_argocd) — no CMP sidecar, no SOPS age
    key — so the plugin lookup fails fast with a ComparisonError:
        `plugin sidecar failed. couldn't find cmp-server plugin with
         name "sops-kustomize" supporting the given repository`
    which trips wait_for_root_app_evaluated and blocks the gate. Stripping
    the plugin name here lets ArgoCD fall back to its built-in kustomize
    handler; comparison succeeds, and any downstream SOPS-Secret sync
    failures land as SyncErrors (advisory in this test) rather than
    ComparisonErrors (fatal). The full SOPS pipeline is exercised on the
    real cluster, not here.
    """
    import re

    return re.sub(
        r"^    plugin:\n      name: sops-kustomize\n?",
        "",
        yaml_text,
        flags=re.MULTILINE,
    )


def _ssh_to_https(url: str) -> str:
    """Rewrite `git@github.com:owner/repo.git` to `https://github.com/owner/repo.git`."""
    if url.startswith("git@github.com:"):
        return "https://github.com/" + url[len("git@github.com:") :]
    return url


def _current_git_sha() -> str:
    res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else ""


def _extract_field(yaml_text: str, key: str) -> str:
    """Naive key extractor — finds the first `<key>: <value>` line.

    Avoids a hard PyYAML dep just for two values. The manifest format is
    stable enough that line-based parsing is safe here.
    """
    import re

    m = re.search(rf"^\s*{re.escape(key)}:\s*(\S+)", yaml_text, re.MULTILINE)
    return m.group(1) if m else ""


def _rewrite_yaml_field(yaml_text: str, key: str, new_value: str) -> str:
    """Replace the first `<key>: <old>` line with `<key>: <new>` in place."""
    import re

    return re.sub(
        rf"^(\s*{re.escape(key)}:\s*)\S+(.*)$",
        rf"\g<1>{new_value}\g<2>",
        yaml_text,
        count=1,
        flags=re.MULTILINE,
    )


def _app_status(name: str, namespace: str = "argocd") -> tuple[str, str]:
    obj = _kubectl_json("-n", namespace, "get", "applications.argoproj.io", name)
    if not obj:
        return "", ""
    status = obj.get("status", {})
    return (
        status.get("sync", {}).get("status", ""),
        status.get("health", {}).get("status", ""),
    )


def wait_for_root_app_synced_healthy(name: str, timeout: int) -> None:
    """Block until root Application is both Synced and Healthy.

    Kept for backwards compatibility with any external caller; the live
    integration test now uses `wait_for_root_app_evaluated` instead. See
    that function's docstring for why we relaxed the gate.
    """
    deadline = time.monotonic() + timeout
    last = ("", "")
    while time.monotonic() < deadline:
        last = _app_status(name)
        if last == ("Synced", "Healthy"):
            return
        time.sleep(5.0)
    raise AssertionError(
        f"root Application {name!r} not Synced+Healthy in {timeout}s "
        f"(last seen: sync={last[0]!r}, health={last[1]!r})"
    )


def _root_app_conditions(name: str, namespace: str = "argocd") -> list[dict]:
    """Return the .status.conditions list for an ArgoCD Application."""
    obj = _kubectl_json("-n", namespace, "get", "applications.argoproj.io", name)
    if not obj:
        return []
    return obj.get("status", {}).get("conditions") or []


def wait_for_root_app_evaluated(name: str, timeout: int) -> None:
    """Block until ArgoCD has *evaluated* the root Application without error.

    Why this exists: the strict `Synced+Healthy` gate (above) demands that
    every dependent operator (Prometheus, Cilium, Falco, Velero, Kyverno…)
    is already installed in the test cluster. Vanilla k3d in CI doesn't
    have those operators, so child apps stay `Missing` forever — but that
    is NOT a manifest bug, just an integration-test gap. The relaxed gate
    here catches the bugs we *do* want to surface pre-merge:

      - broken kustomize → ComparisonError on the Application
      - bad git ref / missing path → ComparisonError
      - malformed CRD definitions → ComparisonError
      - sync-wave drift / circular refs → ComparisonError

    Returns once `status.sync.status` is non-empty (= ArgoCD attempted a
    comparison) AND no ComparisonError is recorded. Raises if a
    ComparisonError appears or the timeout expires before any sync
    verdict is rendered.
    """
    deadline = time.monotonic() + timeout
    last_sync = ""
    while time.monotonic() < deadline:
        sync, _ = _app_status(name)
        last_sync = sync
        conds = _root_app_conditions(name)
        comparison_errors = [c for c in conds if c.get("type") == "ComparisonError"]
        if comparison_errors:
            details = "\n".join(
                f"  - {c.get('type')}: {c.get('message', '')}"
                for c in comparison_errors
            )
            raise AssertionError(
                f"root Application {name!r} reported ComparisonError(s) — "
                f"this is a pre-merge bug class:\n{details}"
            )
        if sync:  # Synced / OutOfSync / Unknown — anything non-empty
            return
        time.sleep(5.0)
    raise AssertionError(
        f"root Application {name!r} never reached an evaluated state in {timeout}s "
        f"(last sync.status={last_sync!r}). ArgoCD comparison controller may be wedged."
    )


def list_unhealthy_applications() -> list[dict]:
    """Return every Application that is not Healthy.

    Each entry: {name, namespace, sync, health, message}. Apps with health
    == 'Missing' due to absent secrets are filtered out when
    `IGNORE_MISSING_SECRET_APPS=1` is set in the env (default: filter on,
    because k3d in CI never has prod SOPS keys).
    """
    ignore_missing = os.environ.get("IGNORE_MISSING_SECRET_APPS", "1") == "1"
    obj = _kubectl_json("get", "applications.argoproj.io", "-A")
    out: list[dict] = []
    for app in obj.get("items", []):
        meta = app["metadata"]
        status = app.get("status", {})
        sync = status.get("sync", {}).get("status", "")
        health = status.get("health", {}).get("status", "")
        if health == "Healthy":
            continue
        if ignore_missing and health == "Missing":
            continue
        out.append(
            {
                "name": meta["name"],
                "namespace": meta["namespace"],
                "sync": sync,
                "health": health,
                "message": status.get("health", {}).get("message", ""),
            }
        )
    return out


def list_applications_with_errors() -> list[dict]:
    """Return Applications with a ComparisonError or SyncError condition.

    Kept for backwards compatibility. New callers should prefer
    `list_apps_with_comparison_errors()` (real bugs) and
    `list_apps_with_sync_errors()` (advisory; CRD-not-found is expected
    on a hermetic k3d).
    """
    error_types = {"ComparisonError", "SyncError"}
    return _list_apps_with_condition_types(error_types)


def list_apps_with_comparison_errors() -> list[dict]:
    """Apps with `ComparisonError` — manifest-level bugs to fail loudly on.

    Caused by: broken kustomize builds, bad git refs, malformed CRDs,
    sync-wave drift, missing target paths. None of these are acceptable
    pre-merge.
    """
    return _list_apps_with_condition_types({"ComparisonError"})


def list_apps_with_sync_errors() -> list[dict]:
    """Apps with `SyncError` — advisory only on a hermetic k3d run.

    Most common cause in CI: `no matches for kind PrometheusRule`-style
    errors when the dependent operator isn't installed in the test
    cluster. Worth surfacing as a workflow log line so the operator
    knows which apps would fail without the operator stack — but NOT
    a pre-merge gate failure.
    """
    return _list_apps_with_condition_types({"SyncError"})


def _list_apps_with_condition_types(types: set[str]) -> list[dict]:
    obj = _kubectl_json("get", "applications.argoproj.io", "-A")
    out: list[dict] = []
    for app in obj.get("items", []):
        meta = app["metadata"]
        for cond in app.get("status", {}).get("conditions", []) or []:
            if cond.get("type") in types:
                out.append(
                    {
                        "name": meta["name"],
                        "namespace": meta["namespace"],
                        "type": cond.get("type"),
                        "message": cond.get("message", ""),
                    }
                )
    return out


def dump_state_for_diagnostics(out_dir) -> None:
    """Best-effort cluster state dump for post-mortem analysis.

    Must run from inside the test (in a try/finally) BEFORE the
    `k3d_cluster` fixture's teardown deletes the cluster. The
    workflow-side post-`failure()` step that previously did this (see
    ci-validation.yml's "Dump ArgoCD State on Failure") was useless —
    by the time it ran, the cluster was already gone.

    Never raises: a diagnostic helper that re-raises in a `finally:`
    block would mask the real assertion error. Errors swallowed.
    """
    from pathlib import Path

    try:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    targets = (
        (
            ["kubectl", "get", "applications.argoproj.io", "-A", "-o", "yaml"],
            "argocd-apps.yaml",
        ),
        (["kubectl", "get", "pods", "-A", "-o", "wide"], "all-pods.txt"),
    )
    for cmd, filename in targets:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            (out_dir / filename).write_text(res.stdout or res.stderr or "")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            # Swallow — we're already in a failure path.
            pass


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    """Manual debug entry point: spin up cluster + report convergence."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a k3d GitOps convergence drill (manual debug tool)."
    )
    parser.add_argument(
        "--cluster", default="homelab-convergence", help="k3d cluster name"
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Don't delete the cluster after run (for inspection).",
    )
    args = parser.parse_args(argv)

    try:
        create_k3d_cluster(args.cluster)
        wait_for_cluster_ready(120)
        apply_argocd()
        wait_for_argocd_server_ready(180)
        apply_root_app()
        wait_for_root_app_synced_healthy("homelab-apps-root", 600)
        unhealthy = list_unhealthy_applications()
        errored = list_applications_with_errors()
        print(json.dumps({"unhealthy": unhealthy, "errored": errored}, indent=2))
        return 1 if (unhealthy or errored) else 0
    except (AssertionError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"convergence failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if not args.keep:
            delete_k3d_cluster(args.cluster)


if __name__ == "__main__":
    raise SystemExit(main())
