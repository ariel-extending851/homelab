#!/usr/bin/env python3
"""Trivy misconfig scanner — k8s + Terraform IaC coverage.

Complements bin/trivy_scan.py (which scans container images for CVEs) by
running `trivy config` over the in-repo IaC sources. Findings filtered by
.trivyignore.yaml at repo root (justified misconfigs with expirations).

Advisory by default — emits a JSON summary to .qa/trivy/ for CI artifact
upload but does not fail the build. Strict mode is reserved for after the
sign-off cycle clears any net-new findings.

Usage:
  python3 bin/trivy_config_scan.py [--paths k8s infra/aws] [--strict]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_PATHS = ["k8s", "infra/aws"]
DEFAULT_OUTPUT_DIR = ".qa/trivy"
DEFAULT_IGNOREFILE = ".trivyignore.yaml"
BLOCKING_SEVERITIES = {"HIGH", "CRITICAL"}


def run_trivy_config(path: str, output_path: Path, ignorefile: str | None) -> dict:
    """Scan one path with trivy config; persist JSON; return parsed dict.

    Trivy auto-discovers `.trivyignore` (line-based, CVE-only) at CWD; we
    pass `.trivyignore.yaml` explicitly because trivy's `--ignorefile`
    default is the line-based file, and the structured YAML is needed for
    per-path misconfig scoping with expirations.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "trivy",
        "config",
        "--severity",
        ",".join(sorted(BLOCKING_SEVERITIES)),
        "--format",
        "json",
        "--output",
        str(output_path),
        "--exit-code",
        "0",
        "--quiet",
    ]
    if ignorefile and Path(ignorefile).exists():
        cmd.extend(["--ignorefile", ignorefile])
    cmd.append(path)
    subprocess.run(cmd, check=True)
    return json.loads(output_path.read_text())


def summarize(report: dict) -> dict:
    """Aggregate misconfig counts by severity for one report."""
    counts = {"HIGH": 0, "CRITICAL": 0}
    findings: list[dict] = []
    for result in report.get("Results", []) or []:
        target = result.get("Target", "?")
        for misc in result.get("Misconfigurations", []) or []:
            sev = misc.get("Severity")
            if sev not in counts:
                continue
            counts[sev] += 1
            findings.append(
                {
                    "target": target,
                    "id": misc.get("ID") or misc.get("AVDID"),
                    "title": misc.get("Title"),
                    "severity": sev,
                    "resolution": misc.get("Resolution"),
                }
            )
    return {"counts": counts, "findings": findings}


def has_blocking(summary: dict) -> bool:
    return summary["counts"]["HIGH"] > 0 or summary["counts"]["CRITICAL"] > 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", nargs="+", default=DEFAULT_PATHS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--ignorefile", default=DEFAULT_IGNOREFILE)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any HIGH/CRITICAL misconfig remains after "
        ".trivyignore.yaml filtering. Default is advisory.",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    aggregate = {"paths": {}, "totals": {"HIGH": 0, "CRITICAL": 0}}
    blocked_any = False

    for path in args.paths:
        if not Path(path).exists():
            print(f"⚠️  Skipping missing path: {path}")
            continue
        print(f"🔍 trivy config {path}...")
        report_path = output_dir / f"config-{path.replace('/', '_')}.json"
        report = run_trivy_config(path, report_path, args.ignorefile)
        summary = summarize(report)
        aggregate["paths"][path] = summary
        aggregate["totals"]["HIGH"] += summary["counts"]["HIGH"]
        aggregate["totals"]["CRITICAL"] += summary["counts"]["CRITICAL"]
        if has_blocking(summary):
            blocked_any = True
            print(
                f"  ⚠️  {path}: HIGH={summary['counts']['HIGH']} "
                f"CRITICAL={summary['counts']['CRITICAL']}"
            )
            for f in summary["findings"][:10]:
                print(
                    f"     - [{f['severity']}] {f['id']} @ {f['target']}: {f['title']}"
                )
        else:
            print(f"  ✅ {path}: clean")

    (output_dir / "config-summary.json").write_text(json.dumps(aggregate, indent=2))
    totals = aggregate["totals"]
    print(
        f"\n📊 Misconfig totals: HIGH={totals['HIGH']} CRITICAL={totals['CRITICAL']} "
        f"(report: {output_dir}/config-summary.json)"
    )

    if blocked_any and not args.strict:
        print("⚠️  Advisory mode — findings reported but build not failed.")
        return 0
    return 1 if blocked_any else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
