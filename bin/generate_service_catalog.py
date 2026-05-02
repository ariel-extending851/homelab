#!/usr/bin/env python3
"""Regenerate the service-catalog table + dependency graph in
docs/services/README.md.

Source of truth is `k8s/apps/<app>/`. For each app directory we extract:
  - **App name** — H1 from `docs/services/<app>.md` if present, else the
    directory name
  - **Doc link** — `<app>.md` if it exists, else `monitoring-stack.md#<app>`
    if the app sits in the `monitoring` namespace, else `—`
  - **Namespace** — from `kustomization.yaml` `namespace:` field, falling
    back to `namespace.yaml`'s `metadata.name`
  - **Ingress** — first host under `spec.tls[0].hosts[0]` from `ingress.yaml`,
    rendered as a Markdown autolink, or `—` when absent
  - **Owner / Tier** — from `catalog-info.yaml` `spec.owner` / `spec.tier`
    (defaults to `—` if the entity is missing)

Two marker-bounded blocks are rewritten in place; everything else
(intro text, footnotes) is preserved verbatim:

  - `<!-- catalog:start -->` / `<!-- catalog:end -->` — the apps table.
  - `<!-- graph:start -->` / `<!-- graph:end -->` — a Mermaid graph
    rendered from `spec.dependsOn` across all `catalog-info.yaml` files.
    The graph block is optional; if the markers are absent, the catalog
    table is updated alone.

Run via `make generate-catalog`. A pre-commit hook fails when the file
drifts so `git diff` is the integration test.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

import yaml

APPS_DIR = Path("k8s/apps")
SERVICES_DOC_DIR = Path("docs/services")
CATALOG_FILE = SERVICES_DOC_DIR / "README.md"
CATALOG_START = "<!-- catalog:start -->"
CATALOG_END = "<!-- catalog:end -->"
GRAPH_START = "<!-- graph:start -->"
GRAPH_END = "<!-- graph:end -->"

# Apps that share `monitoring-stack.md` rather than having their own page.
# Anchor matches the heading slug used in that doc.
MONITORING_STACK_FALLBACK = {
    "blackbox": "monitoring-stack.md#blackbox",
    "kube-state-metrics": "monitoring-stack.md#kube-state-metrics",
    "node-exporter": "monitoring-stack.md#node-exporter",
    "otel-collector": "monitoring-stack.md#otel-collector",
    "prometheus": "monitoring-stack.md#prometheus",
}


def _read_yaml(path: Path) -> Optional[dict]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, yaml.YAMLError):
        return None


def _extract_namespace(app_dir: Path) -> str:
    """Prefer `namespace:` in kustomization.yaml; fall back to namespace.yaml."""
    kust = _read_yaml(app_dir / "kustomization.yaml") or {}
    if isinstance(kust, dict) and kust.get("namespace"):
        return str(kust["namespace"])

    ns_doc = _read_yaml(app_dir / "namespace.yaml") or {}
    if isinstance(ns_doc, dict):
        meta = ns_doc.get("metadata") or {}
        if meta.get("name"):
            return str(meta["name"])
    return "—"


def _extract_ingress_host(app_dir: Path) -> Optional[str]:
    ingress = _read_yaml(app_dir / "ingress.yaml")
    if not isinstance(ingress, dict):
        return None
    spec = ingress.get("spec") or {}
    tls = spec.get("tls") or []
    if not tls:
        return None
    hosts = (tls[0] or {}).get("hosts") or []
    return hosts[0] if hosts else None


def _extract_display_name(app_dir_name: str) -> str:
    """H1 from docs/services/<app>.md if present, else the dir name."""
    doc = SERVICES_DOC_DIR / f"{app_dir_name}.md"
    if doc.is_file():
        for line in doc.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
    return app_dir_name


def _doc_link(app_dir_name: str) -> str:
    own_doc = SERVICES_DOC_DIR / f"{app_dir_name}.md"
    if own_doc.is_file():
        return f"[{app_dir_name}.md]({app_dir_name}.md)"
    if app_dir_name in MONITORING_STACK_FALLBACK:
        target = MONITORING_STACK_FALLBACK[app_dir_name]
        return f"[monitoring-stack.md]({target})"
    return "—"


def _extract_entity(app_dir: Path) -> dict:
    """Return parsed catalog-info.yaml (dict) or an empty dict."""
    raw = _read_yaml(app_dir / "catalog-info.yaml") or {}
    return raw if isinstance(raw, dict) else {}


def collect_rows(base_dir: Path) -> list[dict]:
    apps_root = base_dir / APPS_DIR
    rows = []
    for entry in sorted(apps_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        # An app dir must have at least a kustomization.yaml.
        if not (entry / "kustomization.yaml").is_file():
            continue

        namespace = _extract_namespace(entry)
        ingress = _extract_ingress_host(entry)
        entity = _extract_entity(entry)
        spec = entity.get("spec") if isinstance(entity, dict) else None
        spec = spec if isinstance(spec, dict) else {}
        owner = spec.get("owner") or "—"
        tier = spec.get("tier") or "—"
        deps: list[str] = []
        for d in spec.get("dependsOn") or []:
            if not isinstance(d, str):
                continue
            _, _, target = d.partition(":")
            target = target or d
            if target:
                deps.append(target)
        meta = entity.get("metadata") if isinstance(entity, dict) else None
        meta = meta if isinstance(meta, dict) else {}
        entity_name = meta.get("name") or entry.name

        rows.append(
            {
                "name": _extract_display_name(entry.name),
                "dir": entry.name,
                "doc": _doc_link(entry.name),
                "namespace": namespace,
                "ingress": f"<https://{ingress}>" if ingress else "—",
                "owner": owner,
                "tier": tier,
                "entity_name": entity_name,
                "depends_on": deps,
            }
        )
    return rows


def render_table(rows: list[dict]) -> str:
    lines = [
        "| App | Doc | Namespace | Ingress | Owner | Tier |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['doc']} | `{r['namespace']}` | {r['ingress']} "
            f"| {r['owner']} | `{r['tier']}` |"
        )
    return "\n".join(lines)


def render_catalog_block(rows: list[dict]) -> str:
    """Marker-bounded block, including the markers themselves."""
    return f"{CATALOG_START}\n{render_table(rows)}\n{CATALOG_END}"


def render_mermaid(rows: list[dict]) -> str:
    """Render a Mermaid `graph LR` of dependsOn edges plus orphan nodes.

    GitHub renders Mermaid natively in Markdown — no extra infra needed.
    Orphans are emitted explicitly so the graph is a complete inventory,
    not just the connected subset.
    """
    edges: list[str] = []
    referenced: set[str] = set()
    for r in rows:
        for dep in r["depends_on"]:
            edges.append(f"  {r['entity_name']} --> {dep}")
            referenced.add(dep)
            referenced.add(r["entity_name"])
    body = ["```mermaid", "graph LR"]
    body.extend(edges)
    for r in rows:
        name = r["entity_name"]
        if name not in referenced:
            body.append(f"  {name}")
    body.append("```")
    return "\n".join(body)


def render_graph_block(rows: list[dict]) -> str:
    return f"{GRAPH_START}\n{render_mermaid(rows)}\n{GRAPH_END}"


_CATALOG_RE = re.compile(
    re.escape(CATALOG_START) + r".*?" + re.escape(CATALOG_END),
    re.DOTALL,
)
_GRAPH_RE = re.compile(
    re.escape(GRAPH_START) + r".*?" + re.escape(GRAPH_END),
    re.DOTALL,
)


def update_catalog_file(base_dir: Path, rows: list[dict]) -> tuple[bool, str]:
    """Rewrite the marker blocks in CATALOG_FILE. Returns (changed, new_text).

    The catalog table block is required; the graph block is rewritten only
    when its markers are present (so the change is opt-in).
    """
    target = base_dir / CATALOG_FILE
    if not target.is_file():
        raise SystemExit(f"❌ {CATALOG_FILE} not found.")

    original = target.read_text(encoding="utf-8")
    if not _CATALOG_RE.search(original):
        raise SystemExit(
            f"❌ {CATALOG_FILE} is missing catalog markers.\n"
            f"   Add `{CATALOG_START}` and `{CATALOG_END}` around the table."
        )

    new_catalog = render_catalog_block(rows)
    updated = _CATALOG_RE.sub(lambda _: new_catalog, original, count=1)

    if _GRAPH_RE.search(updated):
        new_graph = render_graph_block(rows)
        updated = _GRAPH_RE.sub(lambda _: new_graph, updated, count=1)

    return updated != original, updated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the catalog is out of sync (do not write).",
    )
    args = parser.parse_args(argv)

    base_dir = Path.cwd()
    rows = collect_rows(base_dir)
    changed, new_text = update_catalog_file(base_dir, rows)

    if args.check:
        if changed:
            print(
                f"❌ {CATALOG_FILE} is out of sync. Run `make generate-catalog`.",
                file=sys.stderr,
            )
            return 1
        print(f"✅ {CATALOG_FILE} is up to date ({len(rows)} apps).")
        return 0

    if changed:
        (base_dir / CATALOG_FILE).write_text(new_text, encoding="utf-8")
        print(f"✅ Updated {CATALOG_FILE} ({len(rows)} apps).")
    else:
        print(f"✅ {CATALOG_FILE} already up to date ({len(rows)} apps).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
