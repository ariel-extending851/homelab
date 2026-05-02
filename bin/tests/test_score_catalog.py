"""Tests for bin/score_catalog.py.

Each rule is exercised with a fixture repo built under tmp_path so the
real `k8s/apps/` tree is never touched. The fixture exposes a small DSL
(`make_app`, `write_entity`) so individual tests stay focused on the
single behavior they assert.
"""

from __future__ import annotations

import io
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import score_catalog as sc  # noqa: E402

# ── fixture builders ────────────────────────────────────────────────────────


def make_app(
    base: Path,
    name: str,
    *,
    namespace: str | None = None,
    deployment: dict | None = None,
    daemonset: dict | None = None,
    ingress: bool = False,
) -> Path:
    """Create a minimal k8s/apps/<name>/ tree under base."""
    app_dir = base / "k8s" / "apps" / name
    app_dir.mkdir(parents=True)
    (app_dir / "kustomization.yaml").write_text(
        f"apiVersion: kustomize.config.k8s.io/v1beta1\n"
        f"kind: Kustomization\nnamespace: {namespace or name}\n",
        encoding="utf-8",
    )
    if namespace:
        (app_dir / "namespace.yaml").write_text(
            f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {namespace}\n",
            encoding="utf-8",
        )
    if ingress:
        (app_dir / "ingress.yaml").write_text(
            "apiVersion: networking.k8s.io/v1\nkind: Ingress\n"
            "spec:\n  tls:\n    - hosts: [example.test]\n",
            encoding="utf-8",
        )
    if deployment is not None:
        (app_dir / "deployment.yaml").write_text(
            _render_workload("Deployment", name, deployment), encoding="utf-8"
        )
    if daemonset is not None:
        (app_dir / "daemonset.yaml").write_text(
            _render_workload("DaemonSet", name, daemonset), encoding="utf-8"
        )
    return app_dir


def _render_workload(kind: str, name: str, opts: dict) -> str:
    """Render a minimal workload manifest. opts keys: probes (bool),
    cpu_limit, mem_limit (str)."""
    probes = opts.get("probes", True)
    cpu_limit = opts.get("cpu_limit", "500m")
    mem_limit = opts.get("mem_limit", "256Mi")
    probe_block = ""
    if probes and kind == "Deployment":
        probe_block = textwrap.indent(
            "livenessProbe:\n"
            "  httpGet: {path: /, port: 8080}\n"
            "readinessProbe:\n"
            "  httpGet: {path: /, port: 8080}\n",
            "        ",
        )
    limits_block = ""
    if cpu_limit or mem_limit:
        parts = []
        if cpu_limit:
            parts.append(f'            cpu: "{cpu_limit}"')
        if mem_limit:
            parts.append(f'            memory: "{mem_limit}"')
        limits_block = (
            "        resources:\n          limits:\n" + "\n".join(parts) + "\n"
        )
    return (
        f"apiVersion: apps/v1\nkind: {kind}\nmetadata:\n  name: {name}\nspec:\n"
        "  template:\n    spec:\n      containers:\n"
        f"      - name: {name}\n"
        f"        image: nginx:latest\n"
        f"{limits_block}"
        f"{probe_block}"
    )


def write_entity(
    app_dir: Path,
    *,
    name: str,
    owner: str = "@team",
    tier: str = "any",
    type_: str = "service",
    lifecycle: str = "production",
    depends_on: list[str] | None = None,
    runbook: str | None = "docs/runbooks/on-call.md",
    doc: str | None = "docs/services/svc.md",
) -> Path:
    annotations: list[str] = []
    if runbook is not None:
        annotations.append(f"    homelab.io/runbook: {runbook}")
    if doc is not None:
        annotations.append(f"    homelab.io/doc: {doc}")
    ann_block = ""
    if annotations:
        ann_block = "  annotations:\n" + "\n".join(annotations) + "\n"
    deps_block = "  dependsOn: []\n"
    if depends_on:
        deps_block = "  dependsOn:\n" + "".join(f"    - {d}\n" for d in depends_on)
    body = (
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        f"metadata:\n  name: {name}\n"
        f"{ann_block}"
        f"spec:\n"
        f"  type: {type_}\n"
        f"  lifecycle: {lifecycle}\n"
        f'  owner: "{owner}"\n'
        f"  tier: {tier}\n"
        f"{deps_block}"
    )
    path = app_dir / "catalog-info.yaml"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    # Prepare runbook + doc that R003/R008 expect by default
    (tmp_path / "docs" / "runbooks").mkdir(parents=True)
    (tmp_path / "docs" / "runbooks" / "on-call.md").write_text(
        "# On-call\n", encoding="utf-8"
    )
    (tmp_path / "docs" / "services").mkdir(parents=True)
    (tmp_path / "docs" / "services" / "svc.md").write_text("# svc\n", encoding="utf-8")
    return tmp_path


# ── helpers ─────────────────────────────────────────────────────────────────


def _findings_by_rule(findings, rule_id):
    return [f for f in findings if f.rule == rule_id]


# ── R001 ────────────────────────────────────────────────────────────────────


def test_R001_passes_when_every_app_has_entity(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha")
    entities = sc.load_entities(repo)
    out = sc.rule_R001(repo, entities)
    assert out == []


def test_R001_fails_for_app_dir_without_entity(repo):
    make_app(repo, "alpha", deployment={})  # no entity written
    entities = sc.load_entities(repo)
    out = sc.rule_R001(repo, entities)
    assert len(out) == 1
    assert out[0].rule == "R001"
    assert out[0].severity == "error"
    assert out[0].component == "alpha"


# ── R002 ────────────────────────────────────────────────────────────────────


def test_R002_fails_when_owner_empty(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", owner="")
    entities = sc.load_entities(repo)
    out = sc.rule_R002(repo, entities)
    assert len(out) == 1
    assert out[0].component == "alpha"


def test_R002_passes_when_owner_set(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", owner="@team")
    entities = sc.load_entities(repo)
    assert sc.rule_R002(repo, entities) == []


# ── R003 ────────────────────────────────────────────────────────────────────


def test_R003_warns_when_runbook_missing_file(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", runbook="docs/runbooks/missing.md")
    entities = sc.load_entities(repo)
    out = sc.rule_R003(repo, entities)
    assert len(out) == 1
    assert out[0].severity == "warning"


def test_R003_warns_when_runbook_annotation_absent(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", runbook=None)
    entities = sc.load_entities(repo)
    out = sc.rule_R003(repo, entities)
    assert len(out) == 1
    assert "not set" in out[0].message


# ── R004 ────────────────────────────────────────────────────────────────────


def test_R004_passes_for_rpi3_within_cap(repo):
    a = make_app(repo, "alpha", deployment={"mem_limit": "256Mi"})
    write_entity(a, name="alpha", tier="rpi3-only")
    entities = sc.load_entities(repo)
    assert sc.rule_R004(repo, entities) == []


def test_R004_fails_for_rpi3_over_cap(repo):
    a = make_app(repo, "alpha", deployment={"mem_limit": "512Mi"})
    write_entity(a, name="alpha", tier="rpi3-only")
    entities = sc.load_entities(repo)
    out = sc.rule_R004(repo, entities)
    assert len(out) == 1
    assert "exceeds" in out[0].message


def test_R004_skips_non_rpi3_apps(repo):
    a = make_app(repo, "alpha", deployment={"mem_limit": "1Gi"})
    write_entity(a, name="alpha", tier="rpi4-or-ec2")
    entities = sc.load_entities(repo)
    assert sc.rule_R004(repo, entities) == []


# ── R005 ────────────────────────────────────────────────────────────────────


def test_R005_fails_when_deployment_missing_probes(repo):
    a = make_app(repo, "alpha", deployment={"probes": False})
    write_entity(a, name="alpha")
    entities = sc.load_entities(repo)
    out = sc.rule_R005(repo, entities)
    assert len(out) == 1
    assert "livenessProbe" in out[0].message


def test_R005_skips_daemonset(repo):
    a = make_app(repo, "alpha", daemonset={"probes": False})
    write_entity(a, name="alpha")
    entities = sc.load_entities(repo)
    assert sc.rule_R005(repo, entities) == []


# ── R006 ────────────────────────────────────────────────────────────────────


def test_R006_fails_when_limits_missing(repo):
    a = make_app(repo, "alpha", deployment={"cpu_limit": None, "mem_limit": None})
    write_entity(a, name="alpha")
    entities = sc.load_entities(repo)
    out = sc.rule_R006(repo, entities)
    assert len(out) == 1
    assert "cpu" in out[0].message and "memory" in out[0].message


def test_R006_passes_with_full_limits(repo):
    a = make_app(repo, "alpha", deployment={"cpu_limit": "500m", "mem_limit": "256Mi"})
    write_entity(a, name="alpha")
    entities = sc.load_entities(repo)
    assert sc.rule_R006(repo, entities) == []


# ── R007 ────────────────────────────────────────────────────────────────────


def test_R007_passes_for_known_dep(repo):
    a = make_app(repo, "alpha", deployment={})
    b = make_app(repo, "beta", deployment={})
    write_entity(a, name="alpha", depends_on=["component:beta"])
    write_entity(b, name="beta")
    entities = sc.load_entities(repo)
    assert sc.rule_R007(repo, entities) == []


def test_R007_fails_for_unknown_dep(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", depends_on=["component:ghost"])
    entities = sc.load_entities(repo)
    out = sc.rule_R007(repo, entities)
    assert len(out) == 1
    assert "ghost" in out[0].message


def test_R007_fails_for_missing_kind_prefix(repo):
    a = make_app(repo, "alpha", deployment={})
    b = make_app(repo, "beta", deployment={})
    write_entity(a, name="alpha", depends_on=["beta"])  # no `component:` prefix
    write_entity(b, name="beta")
    entities = sc.load_entities(repo)
    out = sc.rule_R007(repo, entities)
    assert len(out) == 1
    assert "missing kind prefix" in out[0].message


# ── R008 ────────────────────────────────────────────────────────────────────


def test_R008_warns_when_ingress_present_but_doc_missing(repo):
    a = make_app(repo, "alpha", deployment={}, ingress=True)
    write_entity(a, name="alpha", doc="docs/services/missing.md")
    entities = sc.load_entities(repo)
    out = sc.rule_R008(repo, entities)
    assert len(out) == 1
    assert out[0].severity == "warning"


def test_R008_skips_apps_without_ingress(repo):
    a = make_app(repo, "alpha", deployment={}, ingress=False)
    write_entity(a, name="alpha", doc=None)
    entities = sc.load_entities(repo)
    assert sc.rule_R008(repo, entities) == []


# ── R009 ────────────────────────────────────────────────────────────────────


def test_R009_fails_for_invalid_lifecycle(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", lifecycle="bogus")
    entities = sc.load_entities(repo)
    out = sc.rule_R009(repo, entities)
    assert any("lifecycle" in f.message for f in out)


def test_R009_fails_for_invalid_tier(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", tier="moon-only")
    entities = sc.load_entities(repo)
    out = sc.rule_R009(repo, entities)
    assert any("tier" in f.message for f in out)


def test_R009_fails_for_invalid_type(repo):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", type_="exotic")
    entities = sc.load_entities(repo)
    out = sc.rule_R009(repo, entities)
    assert any("type" in f.message for f in out)


# ── runner / rendering ──────────────────────────────────────────────────────


def test_run_all_aggregates_findings(repo):
    a = make_app(repo, "alpha", deployment={"probes": False})
    write_entity(a, name="alpha", owner="")  # R002 + R005 should fire
    entities = sc.load_entities(repo)
    findings = sc.run_all(repo, entities)
    rules = {f.rule for f in findings}
    assert "R002" in rules
    assert "R005" in rules


def test_run_all_respects_rule_filter(repo):
    a = make_app(repo, "alpha", deployment={"probes": False})
    write_entity(a, name="alpha", owner="")
    entities = sc.load_entities(repo)
    findings = sc.run_all(repo, entities, rule_filter={"R002"})
    assert {f.rule for f in findings} == {"R002"}


def test_render_report_clean(repo):
    buf = io.StringIO()
    sc.render_report([], total_entities=3, out=buf)
    assert "all rules passed" in buf.getvalue()
    assert "(3 components)" in buf.getvalue()


def test_render_report_with_findings():
    buf = io.StringIO()
    findings = [
        sc.Finding("R002", "error", "alpha", "owner missing"),
        sc.Finding("R003", "warning", "alpha", "runbook absent"),
    ]
    sc.render_report(findings, total_entities=1, out=buf)
    text = buf.getvalue()
    assert "R002" in text and "R003" in text
    assert "1 error(s), 1 warning(s)" in text


def test_main_returns_1_when_errors_present(repo, monkeypatch, capsys):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", owner="")
    rc = sc.main([])
    assert rc == 1
    captured = capsys.readouterr()
    assert "R002" in captured.out


def test_main_returns_0_when_only_warnings(repo, capsys):
    a = make_app(repo, "alpha", deployment={})
    write_entity(a, name="alpha", runbook="docs/runbooks/missing.md")
    rc = sc.main([])
    assert rc == 0  # R003 is warning-only


def test_main_app_filter(repo, capsys):
    a = make_app(repo, "alpha", deployment={})
    b = make_app(repo, "beta", deployment={})
    write_entity(a, name="alpha", owner="")
    write_entity(b, name="beta", owner="")
    rc = sc.main(["--app", "alpha"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "alpha" in out
    assert "beta" not in out


def test_parse_memory_mi_handles_units():
    assert sc._parse_memory_mi("256Mi") == 256
    assert sc._parse_memory_mi("1Gi") == 1024
    assert sc._parse_memory_mi("nonsense") is None
    assert sc._parse_memory_mi(None) is None
