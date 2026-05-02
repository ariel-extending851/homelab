"""Tests for bin/generate_service_catalog.py.

Builds a fake `k8s/apps/` tree and verifies the generator produces the
expected marker-bounded markdown. Also covers --check mode and the
"missing markers" failure path.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import generate_service_catalog as gsc  # noqa: E402

# ── helpers ──────────────────────────────────────────────────────────────────


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_app(
    base: Path,
    name: str,
    namespace: str | None = None,
    ingress_host: str | None = None,
    own_doc_h1: str | None = None,
    omit_kustomization: bool = False,
):
    app_dir = base / "k8s" / "apps" / name
    app_dir.mkdir(parents=True)

    if not omit_kustomization:
        kust = "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
        if namespace:
            kust += f"namespace: {namespace}\n"
        _write(app_dir / "kustomization.yaml", kust)

    if namespace:
        _write(
            app_dir / "namespace.yaml",
            f"apiVersion: v1\nkind: Namespace\nmetadata:\n  name: {namespace}\n",
        )

    if ingress_host:
        _write(
            app_dir / "ingress.yaml",
            "apiVersion: networking.k8s.io/v1\nkind: Ingress\n"
            "spec:\n"
            "  tls:\n"
            f"    - hosts: [{ingress_host}]\n",
        )

    if own_doc_h1 is not None:
        _write(base / "docs" / "services" / f"{name}.md", f"# {own_doc_h1}\n")


def _seed_catalog_file(base: Path, *, with_markers: bool = True) -> Path:
    target = base / "docs" / "services" / "README.md"
    intro = "# Services\n\nIntro text.\n\n"
    block = (
        f"{gsc.CATALOG_START}\n(placeholder)\n{gsc.CATALOG_END}\n"
        if with_markers
        else "(no markers here)\n"
    )
    outro = "\nFootnote.\n"
    _write(target, intro + block + outro)
    return target


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Provide a tmp repo with cwd set there for the duration of the test."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ── unit pieces ──────────────────────────────────────────────────────────────


def test_extract_namespace_from_kustomization(repo):
    _make_app(repo, "alpha", namespace="alpha-ns")
    rows = gsc.collect_rows(repo)
    assert rows[0]["namespace"] == "alpha-ns"


def test_extract_namespace_falls_back_to_namespace_yaml(repo):
    app = repo / "k8s" / "apps" / "beta"
    app.mkdir(parents=True)
    _write(app / "kustomization.yaml", "kind: Kustomization\n")
    _write(
        app / "namespace.yaml",
        "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: beta-ns\n",
    )
    rows = gsc.collect_rows(repo)
    assert rows[0]["namespace"] == "beta-ns"


def test_collect_rows_skips_dirs_without_kustomization(repo):
    _make_app(repo, "alpha", namespace="alpha")
    _make_app(repo, "broken", omit_kustomization=True)
    names = [r["dir"] for r in gsc.collect_rows(repo)]
    assert names == ["alpha"]


def test_collect_rows_skips_hidden_dirs(repo):
    _make_app(repo, ".scratch", namespace="ignored")
    _make_app(repo, "alpha", namespace="alpha")
    names = [r["dir"] for r in gsc.collect_rows(repo)]
    assert names == ["alpha"]


def test_display_name_uses_h1_from_own_doc(repo):
    _make_app(repo, "alpha", namespace="alpha", own_doc_h1="Alpha App")
    rows = gsc.collect_rows(repo)
    assert rows[0]["name"] == "Alpha App"


def test_display_name_falls_back_to_dir(repo):
    _make_app(repo, "alpha", namespace="alpha")
    rows = gsc.collect_rows(repo)
    assert rows[0]["name"] == "alpha"


def test_doc_link_uses_monitoring_fallback_when_no_own_doc(repo):
    # `prometheus` is in MONITORING_STACK_FALLBACK
    _make_app(repo, "prometheus", namespace="prometheus")
    rows = gsc.collect_rows(repo)
    assert "monitoring-stack.md#prometheus" in rows[0]["doc"]


def test_doc_link_dash_when_unknown_and_undocumented(repo):
    _make_app(repo, "wholly-new-app", namespace="wholly-new-app")
    rows = gsc.collect_rows(repo)
    assert rows[0]["doc"] == "—"


def test_ingress_extracted_when_present(repo):
    _make_app(
        repo,
        "alpha",
        namespace="alpha",
        ingress_host="alpha.example.com",
        own_doc_h1="Alpha",
    )
    rows = gsc.collect_rows(repo)
    assert rows[0]["ingress"] == "<https://alpha.example.com>"


def test_ingress_dash_when_absent(repo):
    _make_app(repo, "alpha", namespace="alpha")
    rows = gsc.collect_rows(repo)
    assert rows[0]["ingress"] == "—"


# ── render & write ───────────────────────────────────────────────────────────


def test_render_table_has_header_and_rows():
    rows = [
        {
            "name": "Alpha",
            "dir": "alpha",
            "doc": "[alpha.md](alpha.md)",
            "namespace": "alpha",
            "ingress": "<https://alpha.example.com>",
            "owner": "@team",
            "tier": "any",
            "entity_name": "alpha",
            "depends_on": [],
        },
    ]
    out = gsc.render_table(rows)
    assert out.splitlines()[0] == "| App | Doc | Namespace | Ingress | Owner | Tier |"
    assert "| Alpha |" in out
    assert "@team" in out
    assert "`any`" in out


def test_update_catalog_file_replaces_only_marker_block(repo):
    _make_app(repo, "alpha", namespace="alpha", own_doc_h1="Alpha")
    target = _seed_catalog_file(repo)
    rows = gsc.collect_rows(repo)
    changed, new_text = gsc.update_catalog_file(repo, rows)
    assert changed is True
    assert "Intro text." in new_text
    assert "Footnote." in new_text
    assert "(placeholder)" not in new_text
    assert "| Alpha |" in new_text


def test_update_catalog_file_idempotent(repo):
    _make_app(repo, "alpha", namespace="alpha", own_doc_h1="Alpha")
    target = _seed_catalog_file(repo)
    rows = gsc.collect_rows(repo)
    _, new_text = gsc.update_catalog_file(repo, rows)
    target.write_text(new_text, encoding="utf-8")

    # Second run on already-fresh file — should report no change.
    changed, _ = gsc.update_catalog_file(repo, rows)
    assert changed is False


def test_update_catalog_file_errors_when_markers_missing(repo):
    _make_app(repo, "alpha", namespace="alpha")
    _seed_catalog_file(repo, with_markers=False)
    rows = gsc.collect_rows(repo)
    with pytest.raises(SystemExit) as excinfo:
        gsc.update_catalog_file(repo, rows)
    assert "missing catalog markers" in str(excinfo.value)


# ── main entry point ─────────────────────────────────────────────────────────


def test_main_writes_when_drifted(repo, capsys):
    _make_app(repo, "alpha", namespace="alpha", own_doc_h1="Alpha")
    _seed_catalog_file(repo)
    rc = gsc.main([])
    assert rc == 0
    assert "Updated" in capsys.readouterr().out


def test_main_check_mode_succeeds_when_in_sync(repo, capsys):
    _make_app(repo, "alpha", namespace="alpha", own_doc_h1="Alpha")
    target = _seed_catalog_file(repo)
    # Bring the file up to date first.
    gsc.main([])

    rc = gsc.main(["--check"])
    assert rc == 0
    assert "up to date" in capsys.readouterr().out


def test_main_check_mode_fails_when_drifted(repo, capsys):
    _make_app(repo, "alpha", namespace="alpha", own_doc_h1="Alpha")
    _seed_catalog_file(repo)
    rc = gsc.main(["--check"])
    assert rc == 1
    assert "out of sync" in capsys.readouterr().err


# ── catalog-info.yaml integration ────────────────────────────────────────────


def _write_entity(
    base: Path,
    name: str,
    *,
    owner: str = "@team",
    tier: str = "any",
    depends_on: list[str] | None = None,
):
    deps_block = "  dependsOn: []\n"
    if depends_on:
        deps_block = "  dependsOn:\n" + "".join(f"    - {d}\n" for d in depends_on)
    body = (
        "apiVersion: backstage.io/v1alpha1\n"
        "kind: Component\n"
        f"metadata:\n  name: {name}\n"
        "spec:\n"
        "  type: service\n"
        "  lifecycle: production\n"
        f'  owner: "{owner}"\n'
        f"  tier: {tier}\n"
        f"{deps_block}"
    )
    _write(base / "k8s" / "apps" / name / "catalog-info.yaml", body)


def test_collect_rows_uses_catalog_info_for_owner_tier_deps(repo):
    _make_app(repo, "alpha", namespace="alpha")
    _make_app(repo, "beta", namespace="beta")
    _write_entity(
        repo,
        "alpha",
        owner="@platform",
        tier="rpi4-or-ec2",
        depends_on=["component:beta"],
    )
    _write_entity(repo, "beta", owner="@data", tier="rpi3-only")
    rows = {r["dir"]: r for r in gsc.collect_rows(repo)}
    assert rows["alpha"]["owner"] == "@platform"
    assert rows["alpha"]["tier"] == "rpi4-or-ec2"
    assert rows["alpha"]["depends_on"] == ["beta"]
    assert rows["beta"]["tier"] == "rpi3-only"


def test_collect_rows_defaults_when_catalog_info_missing(repo):
    _make_app(repo, "alpha", namespace="alpha")
    rows = gsc.collect_rows(repo)
    assert rows[0]["owner"] == "—"
    assert rows[0]["tier"] == "—"
    assert rows[0]["depends_on"] == []


def test_render_mermaid_includes_edges_and_orphans():
    rows = [
        {"entity_name": "alpha", "depends_on": ["beta"]},
        {"entity_name": "beta", "depends_on": []},
        {"entity_name": "gamma", "depends_on": []},  # orphan
    ]
    out = gsc.render_mermaid(rows)
    assert "graph LR" in out
    assert "alpha --> beta" in out
    assert "  gamma" in out  # orphan listed


def test_update_catalog_file_rewrites_graph_block_when_present(repo):
    _make_app(repo, "alpha", namespace="alpha")
    _make_app(repo, "beta", namespace="beta")
    _write_entity(repo, "alpha", depends_on=["component:beta"])
    _write_entity(repo, "beta")
    target = repo / "docs" / "services" / "README.md"
    intro = "# Services\n\nIntro.\n\n"
    catalog_block = f"{gsc.CATALOG_START}\nold table\n{gsc.CATALOG_END}\n\n"
    graph_block = f"{gsc.GRAPH_START}\nold graph\n{gsc.GRAPH_END}\n"
    _write(target, intro + catalog_block + graph_block)
    rows = gsc.collect_rows(repo)
    changed, new_text = gsc.update_catalog_file(repo, rows)
    assert changed is True
    assert "alpha --> beta" in new_text
    assert "old graph" not in new_text


def test_update_catalog_file_skips_graph_when_markers_absent(repo):
    _make_app(repo, "alpha", namespace="alpha")
    _seed_catalog_file(repo)  # no graph markers
    rows = gsc.collect_rows(repo)
    _, new_text = gsc.update_catalog_file(repo, rows)
    assert gsc.GRAPH_START not in new_text  # not added
    assert gsc.CATALOG_START in new_text  # but catalog still there
