#!/usr/bin/env python3
"""Gate a PR on Terraform cost delta computed by `infracost diff --format json`.

Reads an Infracost diff JSON file, extracts the monthly cost delta, compares
its absolute value against a threshold (USD/month), and exits non-zero when
exceeded. Optionally writes a Markdown summary to a path (useful for
GITHUB_STEP_SUMMARY).

Usage:
    bin/infracost_diff_gate.py \\
        --diff /tmp/infracost-diff.json \\
        --max-delta 5 \\
        --summary "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def extract_delta(diff_path: Path) -> tuple[float, float, float]:
    """Return (base_cost, pr_cost, delta) in USD/month. Missing keys default to 0."""
    data = json.loads(diff_path.read_text())
    pr = float(data.get("totalMonthlyCost") or 0)
    delta = float(data.get("diffTotalMonthlyCost") or 0)
    base = pr - delta
    return base, pr, delta


def render_summary(
    base: float, pr: float, delta: float, max_delta: float, exceeded: bool
) -> str:
    arrow = "+" if delta >= 0 else ""
    status = "❌ OVER LIMIT" if exceeded else "✅ within limit"
    return (
        f"## Infracost Gate — {status}\n\n"
        f"| Metric | USD/month |\n"
        f"|---|---|\n"
        f"| Baseline | {base:.2f} |\n"
        f"| This PR  | {pr:.2f} |\n"
        f"| **Delta** | **{arrow}{delta:.2f}** |\n"
        f"| Threshold | ±{max_delta:.2f} |\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--diff",
        required=True,
        type=Path,
        help="Infracost diff JSON (output of `infracost diff --format json`)",
    )
    parser.add_argument(
        "--max-delta",
        required=True,
        type=float,
        help="Maximum allowed |delta| in USD/month",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=None,
        help="Path to write Markdown summary (e.g., $GITHUB_STEP_SUMMARY)",
    )
    args = parser.parse_args(argv)

    if not args.diff.exists():
        print(f"❌ Diff file not found: {args.diff}", file=sys.stderr)
        return 2

    base, pr, delta = extract_delta(args.diff)
    exceeded = abs(delta) > args.max_delta

    summary = render_summary(base, pr, delta, args.max_delta, exceeded)
    print(summary)

    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(summary + "\n")

    if exceeded:
        print(
            f"\n❌ Cost delta {delta:+.2f} USD/month exceeds threshold "
            f"±{args.max_delta:.2f}. Add label 'cost-approved' to bypass.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
