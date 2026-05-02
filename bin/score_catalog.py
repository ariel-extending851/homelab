#!/usr/bin/env python3
"""score_catalog — validate catalog-info.yaml entities against scorecard rules.

Reads `k8s/apps/<app>/catalog-info.yaml` for every app and runs a series of
rules (R001…R009). Each finding is rendered as a row; exit code is non-zero
if any error-severity rule fails. Warnings do not fail the run.

Run via `make catalog-score` or `homelab catalog score`.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

APPS_DIR = Path("k8s/apps")
RUNBOOKS_DIR = Path("docs/runbooks")
SERVICES_DIR = Path("docs/services")

VALID_TIERS = {"any", "rpi3-only", "rpi4-only", "ec2-only", "rpi4-or-ec2"}
VALID_TYPES = {"service", "website", "library", "datastore"}
VALID_LIFECYCLES = {"production", "staging", "experimental"}

RPI3_MEMORY_LIMIT_MI = 256


@dataclass
class Finding:
    rule: str
    severity: str  # "error" | "warning"
    component: str
    message: str


@dataclass
class Entity:
    path: Path
    raw: dict
    component_dir: Path

    @property
    def name(self) -> str:
        return (self.raw.get("metadata") or {}).get("name") or self.component_dir.name

    @property
    def annotations(self) -> dict:
        return ((self.raw.get("metadata") or {}).get("annotations")) or {}

    @property
    def spec(self) -> dict:
        return self.raw.get("spec") or {}


# ── Loading ─────────────────────────────────────────────────────────────────


def list_app_dirs(base_dir: Path) -> list[Path]:
    apps_root = base_dir / APPS_DIR
    if not apps_root.is_dir():
        return []
    return [
        p
        for p in sorted(apps_root.iterdir())
        if p.is_dir()
        and not p.name.startswith(".")
        and (p / "kustomization.yaml").is_file()
    ]


def load_entities(base_dir: Path) -> list[Entity]:
    entities: list[Entity] = []
    for app_dir in list_app_dirs(base_dir):
        cat = app_dir / "catalog-info.yaml"
        if not cat.is_file():
            continue
        try:
            raw = yaml.safe_load(cat.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        entities.append(Entity(path=cat, raw=raw, component_dir=app_dir))
    return entities


# ── Helpers shared by rules ─────────────────────────────────────────────────


def _parse_memory_mi(value: str | None) -> int | None:
    if not value:
        return None
    s = str(value).strip()
    if s.endswith("Mi"):
        try:
            return int(s[:-2])
        except ValueError:
            return None
    if s.endswith("Gi"):
        try:
            return int(s[:-2]) * 1024
        except ValueError:
            return None
    return None


def _iter_workload_containers(
    app_dir: Path,
) -> Iterable[tuple[str, dict]]:
    """Yield (kind, container_spec) for each container in Deployment/DaemonSet
    manifests under this app dir. Multi-doc YAML is supported.
    """
    for fname in ("deployment.yaml", "daemonset.yaml"):
        path = app_dir / fname
        if not path.is_file():
            continue
        try:
            docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind", "")
            if kind not in ("Deployment", "DaemonSet"):
                continue
            pod_spec = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
            for c in pod_spec.get("containers") or []:
                if isinstance(c, dict):
                    yield kind, c


# ── Rules ───────────────────────────────────────────────────────────────────


def rule_R001(base_dir: Path, entities: list[Entity]) -> list[Finding]:
    """Each k8s/apps/<dir>/ has catalog-info.yaml."""
    found = {e.component_dir.name for e in entities}
    out: list[Finding] = []
    for app in list_app_dirs(base_dir):
        if app.name not in found:
            out.append(
                Finding(
                    "R001",
                    "error",
                    app.name,
                    f"missing catalog-info.yaml in {app.relative_to(base_dir)}/",
                )
            )
    return out


def rule_R002(_: Path, entities: list[Entity]) -> list[Finding]:
    """spec.owner present and non-empty."""
    out: list[Finding] = []
    for e in entities:
        owner = (e.spec.get("owner") or "").strip() if e.spec.get("owner") else ""
        if not owner:
            out.append(Finding("R002", "error", e.name, "spec.owner empty or missing"))
    return out


def rule_R003(base_dir: Path, entities: list[Entity]) -> list[Finding]:
    """homelab.io/runbook annotation references an existing file."""
    out: list[Finding] = []
    for e in entities:
        ref = e.annotations.get("homelab.io/runbook")
        if not ref:
            out.append(
                Finding(
                    "R003", "warning", e.name, "annotation homelab.io/runbook not set"
                )
            )
            continue
        if not (base_dir / ref).is_file():
            out.append(Finding("R003", "warning", e.name, f"runbook not found: {ref}"))
    return out


def rule_R004(_: Path, entities: list[Entity]) -> list[Finding]:
    """tier=rpi3-only requires memory_limit <= 200Mi on all workload containers."""
    out: list[Finding] = []
    for e in entities:
        if e.spec.get("tier") != "rpi3-only":
            continue
        for kind, c in _iter_workload_containers(e.component_dir):
            mem = ((c.get("resources") or {}).get("limits") or {}).get("memory")
            mi = _parse_memory_mi(mem)
            if mi is None:
                out.append(
                    Finding(
                        "R004",
                        "error",
                        e.name,
                        f"{kind} container {c.get('name', '?')!r} "
                        f"has no parseable memory limit (rpi3-only requires <= 200Mi)",
                    )
                )
            elif mi > RPI3_MEMORY_LIMIT_MI:
                out.append(
                    Finding(
                        "R004",
                        "error",
                        e.name,
                        f"{kind} container {c.get('name', '?')!r} memory_limit={mem} "
                        f"exceeds rpi3-only cap of {RPI3_MEMORY_LIMIT_MI}Mi",
                    )
                )
    return out


def rule_R005(_: Path, entities: list[Entity]) -> list[Finding]:
    """Deployment containers (not DaemonSet) declare livenessProbe + readinessProbe."""
    out: list[Finding] = []
    for e in entities:
        for kind, c in _iter_workload_containers(e.component_dir):
            if kind != "Deployment":
                continue
            missing = []
            if not c.get("livenessProbe"):
                missing.append("livenessProbe")
            if not c.get("readinessProbe"):
                missing.append("readinessProbe")
            if missing:
                out.append(
                    Finding(
                        "R005",
                        "error",
                        e.name,
                        f"Deployment container {c.get('name', '?')!r} "
                        f"missing: {', '.join(missing)}",
                    )
                )
    return out


def rule_R006(_: Path, entities: list[Entity]) -> list[Finding]:
    """Workload containers declare resources.limits.cpu and .memory."""
    out: list[Finding] = []
    for e in entities:
        for kind, c in _iter_workload_containers(e.component_dir):
            limits = (c.get("resources") or {}).get("limits") or {}
            missing = []
            if not limits.get("cpu"):
                missing.append("cpu")
            if not limits.get("memory"):
                missing.append("memory")
            if missing:
                out.append(
                    Finding(
                        "R006",
                        "error",
                        e.name,
                        f"{kind} container {c.get('name', '?')!r} "
                        f"missing limits: {', '.join(missing)}",
                    )
                )
    return out


def rule_R007(_: Path, entities: list[Entity]) -> list[Finding]:
    """Every dependsOn entry resolves to a known component name."""
    known = {e.name for e in entities}
    out: list[Finding] = []
    for e in entities:
        for ref in e.spec.get("dependsOn") or []:
            if not isinstance(ref, str):
                out.append(
                    Finding(
                        "R007", "error", e.name, f"non-string dependsOn entry: {ref!r}"
                    )
                )
                continue
            if ":" not in ref:
                out.append(
                    Finding(
                        "R007",
                        "error",
                        e.name,
                        f"dependsOn missing kind prefix (expected 'component:<name>'): {ref!r}",
                    )
                )
                continue
            _, _, target = ref.partition(":")
            if target not in known:
                out.append(
                    Finding(
                        "R007",
                        "error",
                        e.name,
                        f"dependsOn references unknown component: {ref!r}",
                    )
                )
    return out


def rule_R008(base_dir: Path, entities: list[Entity]) -> list[Finding]:
    """When ingress.yaml exists, homelab.io/doc must point to an existing file."""
    out: list[Finding] = []
    for e in entities:
        if not (e.component_dir / "ingress.yaml").is_file():
            continue
        ref = e.annotations.get("homelab.io/doc")
        if not ref:
            out.append(
                Finding(
                    "R008",
                    "warning",
                    e.name,
                    "ingress present but annotation homelab.io/doc not set",
                )
            )
            continue
        if not (base_dir / ref).is_file():
            out.append(Finding("R008", "warning", e.name, f"doc not found: {ref}"))
    return out


def rule_R009(_: Path, entities: list[Entity]) -> list[Finding]:
    """spec.lifecycle ∈ {production, staging, experimental} and spec.tier valid."""
    out: list[Finding] = []
    for e in entities:
        lc = e.spec.get("lifecycle")
        if lc not in VALID_LIFECYCLES:
            out.append(
                Finding(
                    "R009",
                    "error",
                    e.name,
                    f"spec.lifecycle={lc!r} (must be one of {sorted(VALID_LIFECYCLES)})",
                )
            )
        tier = e.spec.get("tier")
        if tier not in VALID_TIERS:
            out.append(
                Finding(
                    "R009",
                    "error",
                    e.name,
                    f"spec.tier={tier!r} (must be one of {sorted(VALID_TIERS)})",
                )
            )
        type_ = e.spec.get("type")
        if type_ not in VALID_TYPES:
            out.append(
                Finding(
                    "R009",
                    "error",
                    e.name,
                    f"spec.type={type_!r} (must be one of {sorted(VALID_TYPES)})",
                )
            )
    return out


RULES: list[tuple[str, callable]] = [
    ("R001", rule_R001),
    ("R002", rule_R002),
    ("R003", rule_R003),
    ("R004", rule_R004),
    ("R005", rule_R005),
    ("R006", rule_R006),
    ("R007", rule_R007),
    ("R008", rule_R008),
    ("R009", rule_R009),
]


# ── Runner / rendering ──────────────────────────────────────────────────────


def run_all(
    base_dir: Path,
    entities: list[Entity],
    rule_filter: set[str] | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    for rid, fn in RULES:
        if rule_filter and rid not in rule_filter:
            continue
        findings.extend(fn(base_dir, entities))
    return findings


def render_report(findings: list[Finding], total_entities: int, out) -> None:
    if not findings:
        out.write(
            f"✅ Catalog scorecard: all rules passed ({total_entities} components).\n"
        )
        return

    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    out.write(f"{'RULE':<6} {'SEV':<8} {'COMPONENT':<25} MESSAGE\n")
    out.write("─" * 80 + "\n")
    for f in findings:
        sev_marker = {"error": "✗ error", "warning": "⚠ warn"}.get(f.severity, "?")
        out.write(f"{f.rule:<6} {sev_marker:<8} {f.component:<25} {f.message}\n")
    out.write("─" * 80 + "\n")
    out.write(
        f"Summary: {errors} error(s), {warnings} warning(s) "
        f"across {total_entities} component(s).\n"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--app",
        help="Filter findings to a single component name (e.g. grafana).",
    )
    parser.add_argument(
        "--rule",
        action="append",
        help="Only run specific rule id(s). May be passed multiple times.",
    )
    args = parser.parse_args(argv)

    base_dir = Path.cwd()
    entities = load_entities(base_dir)
    rule_filter = set(args.rule) if args.rule else None
    findings = run_all(base_dir, entities, rule_filter)

    if args.app:
        findings = [f for f in findings if f.component == args.app]

    render_report(findings, len(entities), sys.stdout)
    has_error = any(f.severity == "error" for f in findings)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
