#!/usr/bin/env python3
"""Generate QA scorecard metrics from QA audit JSON artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DURATION_BUDGETS_SECONDS: dict[str, int] = {
    "contracts": 60,
    "terraform": 180,
    "security": 60,
    "shell": 90,
    "python": 900,
    "e2e_live": 600,
    # disaster_recovery and performance intentionally omitted: both are
    # `required=no` in qa_test_audit.py (TESTS_BASE), so a slow run already
    # produces an advisory, not a gating signal. Enforcing a duration budget
    # on top of that double-gates an advisory suite. Self-hosted pc-tower
    # runners (2 vCPU per replica) push DR/Molecule wall time to ~200s and
    # would trip the historical 60s budget; treating them like the other
    # advisory suites avoids blocking the entire PR queue on a slowdown that
    # isn't a regression in product code.
}


def load_audit_files(input_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    files = sorted(input_dir.glob("qa-audit-*.json"))
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            loaded.append((path, payload))
        except (OSError, json.JSONDecodeError):
            continue
    return loaded


def parse_timestamp(audit: dict[str, Any], fallback: str) -> str:
    ts = str(audit.get("timestamp_utc") or "").strip()
    if ts:
        return ts
    return fallback


def compute_run_metrics(audit: dict[str, Any]) -> dict[str, Any]:
    results = audit.get("results", []) or []
    required = [r for r in results if str(r.get("required", "")).lower() == "yes"]
    required_total = len(required)
    required_passed = sum(1 for r in required if r.get("status") == "passed")
    required_failed = sum(1 for r in required if r.get("status") == "failed")
    required_skipped = sum(1 for r in required if r.get("status") == "skipped")
    required_pass_rate = (
        (required_passed / required_total * 100.0) if required_total else 0.0
    )
    required_skip_rate = (
        (required_skipped / required_total * 100.0) if required_total else 0.0
    )
    total_duration = sum(int(r.get("duration_seconds", 0) or 0) for r in results)

    return {
        "required_total": required_total,
        "required_passed": required_passed,
        "required_failed": required_failed,
        "required_skipped": required_skipped,
        "required_pass_rate": round(required_pass_rate, 2),
        "required_skip_rate": round(required_skip_rate, 2),
        "total_duration_seconds": total_duration,
        "required_skip_details": [
            {
                "suite": r.get("suite"),
                "reason": r.get("skip_reason") or "NO_REASON_CODE",
            }
            for r in required
            if r.get("status") == "skipped"
        ],
    }


def compute_flake_rate(recent: list[dict[str, Any]]) -> float:
    statuses_by_suite: dict[str, set[str]] = {}
    required_suites: set[str] = set()

    for run in recent:
        for result in run.get("results", []) or []:
            if str(result.get("required", "")).lower() != "yes":
                continue
            suite = str(result.get("suite", "")).strip()
            if not suite:
                continue
            required_suites.add(suite)
            statuses_by_suite.setdefault(suite, set()).add(
                str(result.get("status", ""))
            )

    if not required_suites:
        return 0.0

    flaky = 0
    for suite in required_suites:
        statuses = statuses_by_suite.get(suite, set())
        if "passed" in statuses and "failed" in statuses:
            flaky += 1

    return round((flaky / len(required_suites)) * 100.0, 2)


def compute_suite_flake_details(recent: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suite_history: dict[str, set[str]] = {}
    suite_runs: dict[str, int] = {}

    for run in recent:
        run_results = run.get("results", []) or []
        seen_in_run: set[str] = set()
        for result in run_results:
            if str(result.get("required", "")).lower() != "yes" and str(
                result.get("suite", "")
            ) not in {"performance", "e2e_live"}:
                continue
            suite = str(result.get("suite", "")).strip()
            if not suite:
                continue
            suite_history.setdefault(suite, set()).add(str(result.get("status", "")))
            if suite not in seen_in_run:
                suite_runs[suite] = suite_runs.get(suite, 0) + 1
                seen_in_run.add(suite)

    details: list[dict[str, Any]] = []
    for suite in sorted(suite_history):
        statuses = suite_history[suite]
        passed = "passed" in statuses
        failed = "failed" in statuses
        skipped = "skipped" in statuses
        details.append(
            {
                "suite": suite,
                "runs": suite_runs.get(suite, 0),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "is_flaky": passed and failed,
            }
        )

    return details


def load_budget_file(budget_file: Path) -> dict[str, int]:
    if not budget_file.exists():
        return {}

    try:
        raw = json.loads(budget_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    budgets: dict[str, int] = {}
    for key, value in raw.items():
        try:
            budgets[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return budgets


def compute_budget_violations(
    latest_results: list[dict[str, Any]],
    budgets: dict[str, int],
    margin_percent: int,
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    effective_budgets: dict[str, int] = dict(DEFAULT_DURATION_BUDGETS_SECONDS)
    effective_budgets.update(budgets)

    for result in latest_results:
        suite = str(result.get("suite", "")).strip()
        if not suite:
            continue
        threshold = effective_budgets.get(suite)
        if threshold is None:
            continue
        observed = int(result.get("duration_seconds", 0) or 0)
        allowed = int(threshold * (1 + margin_percent / 100.0))
        if observed > allowed:
            violations.append(
                {
                    "suite": suite,
                    "observed_seconds": observed,
                    "allowed_seconds": allowed,
                    "threshold_seconds": threshold,
                }
            )

    return violations


def write_outputs(
    input_dir: Path,
    latest_name: str,
    scorecard: dict[str, Any],
    markdown: str,
) -> tuple[Path, Path, Path, Path]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_ts = input_dir / f"qa-scorecard-{ts}.json"
    md_ts = input_dir / f"qa-scorecard-{ts}.md"
    json_latest = input_dir / "qa-scorecard-latest.json"
    md_latest = input_dir / "qa-scorecard-latest.md"

    json_blob = json.dumps(scorecard, indent=2)
    json_ts.write_text(json_blob + "\n", encoding="utf-8")
    md_ts.write_text(markdown, encoding="utf-8")
    json_latest.write_text(json_blob + "\n", encoding="utf-8")
    md_latest.write_text(markdown, encoding="utf-8")

    print("QA scorecard generated:")
    print(f"- {md_ts}")
    print(f"- {json_ts}")
    print(f"- {md_latest}")
    print(f"- {json_latest}")
    print(f"- source latest audit: {latest_name}")

    return md_ts, json_ts, md_latest, json_latest


def build_markdown(scorecard: dict[str, Any]) -> str:
    latest = scorecard["latest_run"]
    metrics = latest["metrics"]
    lines = [
        "# QA Scorecard",
        "",
        f"- Generated (UTC): {scorecard['generated_utc']}",
        f"- History window: {scorecard['history_limit']} runs",
        f"- Latest audit: {latest['audit_file']}",
        f"- Latest audit timestamp: {latest['timestamp_utc']}",
        "",
        "## Latest Metrics",
        "",
        f"- Required pass rate: {metrics['required_pass_rate']}%",
        f"- Required skip rate: {metrics['required_skip_rate']}%",
        f"- Required total/passed/failed/skipped: {metrics['required_total']}/{metrics['required_passed']}/{metrics['required_failed']}/{metrics['required_skipped']}",
        f"- Total suite duration: {metrics['total_duration_seconds']}s",
        f"- Flake rate (history): {scorecard['flake_rate_percent']}%",
        "",
        "## Duration Budgets",
        "",
        f"- Margin: {scorecard['duration_budget_margin_percent']}%",
        f"- Violations: {len(scorecard['latest_run'].get('duration_budget_violations', []))}",
        "",
        "## Flake Details",
        "",
        "| Suite | Runs | Passed | Failed | Skipped | Flaky |",
        "|---|---:|---|---|---|---|",
    ]

    for row in scorecard["flake_by_suite"]:
        lines.append(
            f"| {row['suite']} | {row['runs']} | {str(row['passed']).lower()} | {str(row['failed']).lower()} | {str(row['skipped']).lower()} | {str(row['is_flaky']).lower()} |"
        )

    lines.extend(
        [
            "",
            "## Last Runs",
            "",
            "| Run | Required Pass Rate | Required Skip Rate | Required Failed | Duration (s) |",
            "|---|---:|---:|---:|---:|",
        ]
    )

    for run in scorecard["history"]:
        m = run["metrics"]
        lines.append(
            f"| {run['timestamp_utc']} | {m['required_pass_rate']} | {m['required_skip_rate']} | {m['required_failed']} | {m['total_duration_seconds']} |"
        )

    if metrics["required_skip_details"]:
        lines.extend(
            [
                "",
                "## Required Skips",
                "",
                "| Suite | Reason |",
                "|---|---|",
            ]
        )
        for row in metrics["required_skip_details"]:
            lines.append(f"| {row['suite']} | {row['reason']} |")

    violations = scorecard["latest_run"].get("duration_budget_violations", [])
    if violations:
        lines.extend(
            [
                "",
                "## Duration Budget Violations",
                "",
                "| Suite | Observed (s) | Allowed (s) | Threshold (s) |",
                "|---|---:|---:|---:|",
            ]
        )
        for row in violations:
            lines.append(
                f"| {row['suite']} | {row['observed_seconds']} | {row['allowed_seconds']} | {row['threshold_seconds']} |"
            )

    lines.append("")
    return "\n".join(lines)


def verify_no_required_skips(latest_metrics: dict[str, Any]) -> int:
    skipped = int(latest_metrics.get("required_skipped", 0))
    if skipped > 0:
        print(f"[FAIL] Required suites skipped: {skipped}")
        for row in latest_metrics.get("required_skip_details", []):
            print(f" - {row.get('suite')}: {row.get('reason')}")
        return 1
    print("[OK] No required suites were skipped")
    return 0


def verify_duration_budgets(latest_violations: list[dict[str, Any]]) -> int:
    if latest_violations:
        print(f"[FAIL] Duration budget violations: {len(latest_violations)}")
        for row in latest_violations:
            print(
                " - {suite}: observed {observed_seconds}s > allowed {allowed_seconds}s (threshold {threshold_seconds}s)".format(
                    **row
                )
            )
        return 1
    print("[OK] No duration budget violations")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build QA scorecard from audit artifacts"
    )
    parser.add_argument(
        "--input-dir", default=".qa/evidence", help="QA evidence directory"
    )
    parser.add_argument(
        "--history-limit",
        type=int,
        default=14,
        help="How many runs to include in history",
    )
    parser.add_argument(
        "--budget-file",
        default=".qa/qa-budgets.json",
        help="Optional budget override file",
    )
    parser.add_argument(
        "--margin-percent",
        type=int,
        default=20,
        help="Allowed margin above duration threshold before failing",
    )
    parser.add_argument(
        "--verify-no-required-skips",
        action="store_true",
        help="Fail if latest audit has required suites with skipped status",
    )
    parser.add_argument(
        "--verify-duration-budgets",
        action="store_true",
        help="Fail if latest audit exceeds suite duration budgets",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    loaded = load_audit_files(input_dir)
    if not loaded:
        print(f"[FAIL] No audit files found in {input_dir}")
        return 1

    recent = loaded[-args.history_limit :]
    history: list[dict[str, Any]] = []
    budgets = load_budget_file(Path(args.budget_file))

    for path, audit in recent:
        results = audit.get("results", []) or []
        duration_violations = compute_budget_violations(
            results, budgets, args.margin_percent
        )
        history.append(
            {
                "audit_file": path.name,
                "timestamp_utc": parse_timestamp(
                    audit, path.stem.replace("qa-audit-", "")
                ),
                "metrics": compute_run_metrics(audit),
                "results": results,
                "duration_budget_violations": duration_violations,
            }
        )

    latest = history[-1]
    flake_rate = compute_flake_rate([h for _, h in loaded[-args.history_limit :]])

    scorecard = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "history_limit": args.history_limit,
        "duration_budget_margin_percent": args.margin_percent,
        "duration_budgets_seconds": {**DEFAULT_DURATION_BUDGETS_SECONDS, **budgets},
        "flake_rate_percent": flake_rate,
        "flake_by_suite": compute_suite_flake_details(
            [h for _, h in loaded[-args.history_limit :]]
        ),
        "latest_run": {
            "audit_file": latest["audit_file"],
            "timestamp_utc": latest["timestamp_utc"],
            "metrics": latest["metrics"],
            "duration_budget_violations": latest["duration_budget_violations"],
        },
        "history": [
            {
                "audit_file": run["audit_file"],
                "timestamp_utc": run["timestamp_utc"],
                "metrics": run["metrics"],
                "duration_budget_violations": run["duration_budget_violations"],
            }
            for run in history
        ],
    }

    markdown = build_markdown(scorecard)
    write_outputs(input_dir, latest["audit_file"], scorecard, markdown)

    if args.verify_no_required_skips:
        result = verify_no_required_skips(latest["metrics"])
        if result != 0:
            return result

    if args.verify_duration_budgets:
        return verify_duration_budgets(latest["duration_budget_violations"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
