#!/usr/bin/env python3
"""Trivy image vulnerability scanner — supply chain gate for K8s manifests.

Extracts container images from `kustomize build k8s/apps`, scans each via
trivy CLI, and exits non-zero if any image has HIGH/CRITICAL CVEs that have
a fix available upstream.

Design:
  - Pure functions for parsing/dedupe/severity filtering (unit-testable)
  - subprocess calls isolated in run_kustomize/run_trivy (mockable)
  - JSON reports persisted in .qa/trivy/ for CI artifacts

Usage:
  python3 bin/trivy_scan.py [--manifests-dir k8s/apps] [--output-dir .qa/trivy]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import yaml

DEFAULT_MANIFESTS_DIR = "k8s/apps"
DEFAULT_OUTPUT_DIR = ".qa/trivy"
BLOCKING_SEVERITIES = {"HIGH", "CRITICAL"}


# ── pure helpers (unit-testable) ────────────────────────────────────────────


def extract_images(rendered_yaml: str) -> list[str]:
    """Parse rendered kustomize YAML and return deduplicated, sorted image refs.

    Walks Deployment/DaemonSet/StatefulSet/Job/CronJob containers and
    initContainers. Skips empty docs and SOPS-encrypted ones.
    """
    images: set[str] = set()
    for doc in yaml.safe_load_all(rendered_yaml):
        if not doc or not isinstance(doc, dict):
            continue
        if "sops" in doc:
            continue
        for image in _images_in_doc(doc):
            images.add(image)
    return sorted(images)


def _images_in_doc(doc: dict) -> Iterable[str]:
    kind = doc.get("kind")
    if kind in {"Deployment", "DaemonSet", "StatefulSet", "Job", "ReplicaSet"}:
        spec = doc.get("spec", {}).get("template", {}).get("spec", {})
    elif kind == "CronJob":
        spec = (
            doc.get("spec", {})
            .get("jobTemplate", {})
            .get("spec", {})
            .get("template", {})
            .get("spec", {})
        )
    elif kind == "Pod":
        spec = doc.get("spec", {})
    else:
        return
    for container in spec.get("containers", []) or []:
        if image := container.get("image"):
            yield image
    for container in spec.get("initContainers", []) or []:
        if image := container.get("image"):
            yield image


def has_blocking_vulns(report: dict) -> bool:
    """True if the trivy JSON report contains any HIGH/CRITICAL CVE with a fix.

    Trivy already filters via --ignore-unfixed at scan time, but this is a
    defensive in-code check so the function is also useful against raw
    unfiltered reports in tests.
    """
    for result in report.get("Results", []) or []:
        for vuln in result.get("Vulnerabilities", []) or []:
            if vuln.get("Severity") not in BLOCKING_SEVERITIES:
                continue
            if not vuln.get("FixedVersion"):
                continue
            return True
    return False


def sanitize_image_name(image: str) -> str:
    """Convert image ref to a filesystem-safe identifier."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", image)


def summarize_report(image: str, report: dict) -> dict:
    """Aggregate counts of HIGH/CRITICAL fixable CVEs for a one-line summary."""
    counts = {"HIGH": 0, "CRITICAL": 0}
    for result in report.get("Results", []) or []:
        for vuln in result.get("Vulnerabilities", []) or []:
            sev = vuln.get("Severity")
            if sev in counts and vuln.get("FixedVersion"):
                counts[sev] += 1
    return {"image": image, "blocking": counts, "blocked": has_blocking_vulns(report)}


# ── subprocess wrappers (mockable in tests) ─────────────────────────────────


def run_kustomize(manifests_dir: str) -> str:
    """Render kustomize manifests; raises CalledProcessError on failure."""
    result = subprocess.run(
        ["kustomize", "build", manifests_dir],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def run_trivy(image: str, output_dir: Path) -> dict:
    """Scan a single image with Trivy; persist JSON report; return parsed dict.

    Uses --ignore-unfixed so CVEs without an upstream patch don't block.
    Uses --severity HIGH,CRITICAL to keep reports focused.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{sanitize_image_name(image)}.json"
    cmd = [
        "trivy",
        "image",
        "--severity",
        "HIGH,CRITICAL",
        "--ignore-unfixed",
        "--format",
        "json",
        "--output",
        str(report_path),
        "--no-progress",
        "--quiet",
        image,
    ]
    subprocess.run(cmd, check=True)
    return json.loads(report_path.read_text())


# ── orchestration ───────────────────────────────────────────────────────────


def scan_all(manifests_dir: str, output_dir: Path) -> tuple[int, list[dict]]:
    """Render manifests, scan every image, return (exit_code, summaries)."""
    rendered = run_kustomize(manifests_dir)
    images = extract_images(rendered)
    if not images:
        print("⚠️  No images found in manifests — nothing to scan.")
        return 0, []

    summaries: list[dict] = []
    blocked_any = False
    for image in images:
        print(f"🔍 Scanning {image}...")
        report = run_trivy(image, output_dir)
        summary = summarize_report(image, report)
        summaries.append(summary)
        if summary["blocked"]:
            blocked_any = True
            counts = summary["blocking"]
            print(
                f"  ❌ {image}: HIGH={counts['HIGH']} CRITICAL={counts['CRITICAL']} (fix available)"
            )
        else:
            print(f"  ✅ {image}: clean")

    (output_dir / "summary.json").write_text(json.dumps(summaries, indent=2))
    return (1 if blocked_any else 0), summaries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifests-dir", default=DEFAULT_MANIFESTS_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any HIGH/CRITICAL fixable CVE. "
        "Default is advisory (always exit 0); strict mode is the eventual gate.",
    )
    args = parser.parse_args(argv)

    raw_exit_code, summaries = scan_all(args.manifests_dir, Path(args.output_dir))
    n_blocked = sum(1 for s in summaries if s["blocked"])
    print(
        f"\n📊 Scanned {len(summaries)} image(s); "
        f"{n_blocked} blocked, {len(summaries) - n_blocked} clean."
    )

    if not args.strict and raw_exit_code != 0:
        print(
            "⚠️  Advisory mode: blocking CVEs found but not failing the build. "
            "Reports in .qa/trivy/. Run with --strict to fail on findings."
        )
        return 0
    return raw_exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
