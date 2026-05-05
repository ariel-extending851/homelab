"""E2E tests for the Tailscale Kubernetes Operator (cluster-side validation).

Companion to the ansible role at `ansible/roles/tailscale_operator`. The
role installs the upstream chart + ProxyClasses; this file asserts the
resulting cluster state is healthy *after* a successful deploy.

Why these tests exist:
    The first prod re-deploy after the role landed (PR #55) shipped what
    *looked* like a green ansible run, but the helm chart was actually in
    CrashLoopBackOff because the OAuth credentials in `values.sops.yaml`
    had been revoked. None of the existing checks caught it — the
    operator namespace isn't an "app" — and the failure only surfaced
    when an operator manually noticed `https://grafana.tail57bf10.ts.net`
    was unreachable. These tests close that gap.

Run after deployment:
    python3 -m pytest bin/tests/test_tailscale_operator_e2e.py --run-live
    # or via the make target:
    make test-e2e-tailscale-operator
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

pytestmark = [pytest.mark.live]

TS_NS = os.environ.get("TS_NS", "tailscale")


# ─────────────────────────────────────────────────────────────────────────
# kubectl helpers (small, local — keeps the test self-contained)
# ─────────────────────────────────────────────────────────────────────────


def _kubectl_json(*args: str) -> dict:
    """Run `kubectl ... -o json` and return the parsed JSON.

    Returns an empty dict on non-zero exit so callers can treat "missing
    resource" as a normal assertion failure path instead of a stack trace.
    """
    result = subprocess.run(
        ["kubectl", *args, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}


def _kubectl_jsonpath(*args: str, path: str) -> str:
    """Run `kubectl ... -o jsonpath=<path>` and return stdout (stripped)."""
    result = subprocess.run(
        ["kubectl", *args, "-o", f"jsonpath={path}"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


# ─────────────────────────────────────────────────────────────────────────
# Module-level pre-flight: skip the whole file when the cluster is gone,
# instead of failing every test individually with a confusing kubectl error.
# ─────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def _cluster_reachable() -> None:
    result = subprocess.run(
        ["kubectl", "cluster-info", "--request-timeout=5s"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            f"cluster unreachable (KUBECONFIG={os.environ.get('KUBECONFIG', '<unset>')})"
        )


# ─────────────────────────────────────────────────────────────────────────
# Operator install — proves the helm chart actually rolled out
# ─────────────────────────────────────────────────────────────────────────


def test_namespace_exists() -> None:
    """The role's helm install creates the `tailscale` namespace."""
    rc = subprocess.run(
        ["kubectl", "get", "namespace", TS_NS],
        capture_output=True,
    ).returncode
    assert rc == 0, f"namespace {TS_NS!r} missing — operator was never installed"


def test_operator_deployment_has_available_replica() -> None:
    """`status.availableReplicas >= 1` proves the rollout completed."""
    raw = _kubectl_jsonpath(
        "-n",
        TS_NS,
        "get",
        "deploy",
        "operator",
        path="{.status.availableReplicas}",
    )
    available = int(raw or 0)
    assert available >= 1, (
        f"operator Deployment has {available} available replicas — "
        "chart probably rolled out but the pod isn't passing its readiness probe"
    )


def test_operator_pod_is_running() -> None:
    """Phase=Running on the `app=operator` selector.

    The chart labels its pod `app=operator` (not
    `app.kubernetes.io/name=tailscale-operator` — see PR #56 for the role's
    selector fix). Use the same label here.
    """
    phase = _kubectl_jsonpath(
        "-n",
        TS_NS,
        "get",
        "pods",
        "-l",
        "app=operator",
        path="{.items[0].status.phase}",
    )
    assert phase == "Running", (
        f"operator pod phase={phase!r} — expected Running. "
        "If empty, the label may have changed upstream; if Pending, an "
        "image pull or node-scheduling problem; if anything else, fetch "
        "logs with: kubectl logs -n tailscale -l app=operator --tail=50"
    )


def test_operator_pod_has_low_restart_count() -> None:
    """Catches CrashLoopBackOff that `phase=Running` reports between restarts.

    Threshold of 3 absorbs the initial scheduler blip but is well below
    the dozens-per-minute rate of an actual crashloop (the 2026-05-05
    OAuth-401 incident).
    """
    raw = _kubectl_jsonpath(
        "-n",
        TS_NS,
        "get",
        "pods",
        "-l",
        "app=operator",
        path="{.items[0].status.containerStatuses[0].restartCount}",
    )
    restarts = int(raw or 0)
    assert restarts <= 3, (
        f"operator pod has {restarts} restarts — likely crashlooping. "
        "Common cause: OAuth credentials in "
        "k8s/system/tailscale-operator/values.sops.yaml are revoked or "
        "missing the `auth_keys`/`devices` scopes."
    )


# ─────────────────────────────────────────────────────────────────────────
# ProxyClass resources — required by ingresses that opt in via label
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["default", "high-bandwidth"])
def test_proxyclass_exists(name: str) -> None:
    """Both ProxyClass CRs land via the role's `proxyclass` task."""
    rc = subprocess.run(
        ["kubectl", "get", "proxyclass", name],
        capture_output=True,
    ).returncode
    assert rc == 0, (
        f"ProxyClass {name!r} missing — the role's `Apply ProxyClass manifests` "
        f"task should have applied k8s/system/tailscale-operator/{name}-proxyclass.yaml"
    )


# ─────────────────────────────────────────────────────────────────────────
# Ingress materialization — the user-visible outcome: a tailnet hostname
# gets assigned to every ingress with `class: tailscale`. This is what
# would have caught the 2026-05-05 evening incident.
# ─────────────────────────────────────────────────────────────────────────


def _materialized_tailscale_ingresses() -> list[dict]:
    """Return the ingresses with class=tailscale that have an ADDRESS populated."""
    payload = _kubectl_json("get", "ingress", "-A")
    items = payload.get("items", []) if isinstance(payload, dict) else []
    out = []
    for ing in items:
        spec = ing.get("spec", {})
        if spec.get("ingressClassName") != "tailscale":
            continue
        lb = ing.get("status", {}).get("loadBalancer", {}).get("ingress") or []
        if lb:
            out.append(ing)
    return out


def test_at_least_one_tailscale_ingress_materialized() -> None:
    """At least one ingress has reached `status.loadBalancer.ingress[0]`.

    This is the operator's actual job: watch ingresses, provision proxies,
    populate the status field. An empty ADDRESS column means the operator
    is running but not reconciling — usually OAuth-scope, ACL, or
    `tag:k8s-operator` misconfiguration.
    """
    materialized = _materialized_tailscale_ingresses()
    assert len(materialized) >= 1, (
        "no Ingress with `class: tailscale` has an ADDRESS populated. "
        "Check `kubectl get ingress -A` and `kubectl logs -n tailscale "
        "-l app=operator --tail=100` for OAuth / tag errors."
    )


def test_proxy_pod_count_matches_materialized_ingresses() -> None:
    """Every materialized ingress should have a `ts-<name>` proxy pod.

    Mismatch suggests a half-broken state: the operator created the
    tailnet device but the proxy pod failed to come up (image pull, RBAC,
    pending PVC, etc.).
    """
    materialized = _materialized_tailscale_ingresses()
    proxy_pods = _kubectl_json("-n", TS_NS, "get", "pods").get("items", [])
    proxy_count = sum(
        1 for p in proxy_pods if p.get("metadata", {}).get("name", "").startswith("ts-")
    )
    assert proxy_count >= len(materialized), (
        f"only {proxy_count} ts-* proxy pod(s) for {len(materialized)} "
        "materialized ingress(es). Run "
        "`kubectl get pods -n tailscale -o wide` and look for proxies "
        "stuck in Pending/CrashLoopBackOff."
    )
