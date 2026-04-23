#!/usr/bin/env python3
"""QA evidence runner: executes test suites sequentially and writes auditable output.

Port of scripts/qa_test_audit.sh. Produces markdown + JSON reports in
.qa/evidence/ whose schema is consumed downstream by scripts/qa_scorecard.py.

Environment variables:
  QA_INCLUDE_LIVE_E2E   "1" to mark e2e_live as required (default: "0")
  QA_OUT_DIR            Output directory (default: .qa/evidence)
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TESTS_BASE = [
    ("contracts", "make test-contracts", "yes"),
    ("terraform", "make test-terraform", "yes"),
    ("security", "make test-security", "yes"),
    ("disaster_recovery", "make test-dr", "no"),
    ("shell", "make test-shell", "yes"),
    ("python", "make test-python", "yes"),
    ("performance", "make test-performance", "no"),
]


def build_test_matrix(include_live_e2e):
    """Append e2e_live with required=yes iff QA_INCLUDE_LIVE_E2E == '1'."""
    required = "yes" if include_live_e2e == "1" else "no"
    return [*TESTS_BASE, ("e2e_live", "make test-e2e-post-deploy", required)]


def git_info():
    """Return (short_commit, branch_name). Falls back to 'unknown' on error."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = "unknown"
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        branch = "unknown"
    return commit, branch


def run_suite(suite_id, command, required, log_file, include_live_e2e):
    """Execute one suite, stream output to log_file, return a schema dict."""
    start = time.time()
    skip_reason = None

    if suite_id == "e2e_live" and include_live_e2e != "1":
        status = "skipped"
        skip_reason = "LIVE_E2E_DISABLED"
        log_file.write_text(
            "Live E2E skipped by default. " "Set QA_INCLUDE_LIVE_E2E=1 to execute.\n"
        )
    else:
        # Match original shell: `bash -lc "${suite_cmd}"` — login shell so
        # PATH and mise/pipx initialization from user profile apply. Using
        # shell=True would route through /bin/sh (dash on Debian) and break
        # bash-specific suites.
        with log_file.open("w") as fh:
            proc = subprocess.run(
                ["bash", "-lc", command], stdout=fh, stderr=subprocess.STDOUT
            )
        status = "passed" if proc.returncode == 0 else "failed"

    duration = int(time.time() - start)
    return {
        "suite": suite_id,
        "command": command,
        "required": required,
        "status": status,
        "duration_seconds": duration,
        "log": str(log_file),
        "skip_reason": skip_reason,
    }


def render_markdown(run_info, results, out_path):
    lines = [
        "# QA Audit Report",
        "",
        f"- Timestamp (UTC): {run_info['timestamp_utc']}",
        f"- Commit: {run_info['commit']}",
        f"- Branch: {run_info['branch']}",
        f"- Include live E2E: {run_info['include_live_e2e']}",
        "",
        "| Suite | Command | Required | Status | Duration (s) | Log |",
        "|---|---|---|---|---:|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['suite']} | {r['command']} | {r['required']} | "
            f"{r['status']} | {r['duration_seconds']} | {r['log']} |"
        )
    out_path.write_text("\n".join(lines) + "\n")


def render_json(run_info, results, required_failures, out_path):
    payload = {
        "timestamp_utc": run_info["timestamp_utc"],
        "commit": run_info["commit"],
        "branch": run_info["branch"],
        "include_live_e2e": run_info["include_live_e2e"],
        "results": results,
        "required_failures": required_failures,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")


def run_audit(out_dir, include_live_e2e, now=None, runner=run_suite):
    now = now or datetime.now(timezone.utc)
    timestamp_utc = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = now.strftime("%Y%m%dT%H%M%SZ")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = out_dir / f"logs-{run_id}"
    log_dir.mkdir(parents=True, exist_ok=True)

    commit, branch = git_info()
    run_info = {
        "timestamp_utc": timestamp_utc,
        "commit": commit,
        "branch": branch,
        "include_live_e2e": include_live_e2e,
    }

    matrix = build_test_matrix(include_live_e2e)
    results = []
    required_failures = 0
    for suite_id, cmd, required in matrix:
        print(f"[QA] Running {suite_id}: {cmd}")
        log_file = log_dir / f"{suite_id}.log"
        result = runner(suite_id, cmd, required, log_file, include_live_e2e)
        results.append(result)
        if required == "yes" and result["status"] == "failed":
            required_failures += 1

    summary_md = out_dir / f"qa-audit-{run_id}.md"
    summary_json = out_dir / f"qa-audit-{run_id}.json"
    render_markdown(run_info, results, summary_md)
    render_json(run_info, results, required_failures, summary_json)

    latest_md = out_dir / "qa-audit-latest.md"
    latest_md.write_text(summary_md.read_text())

    print()
    print("QA evidence generated:")
    print(f"- {summary_md}")
    print(f"- {summary_json}")
    print(f"- {log_dir}/")

    if required_failures > 0:
        print()
        print(f"[QA] Required suites failed: {required_failures}")
        return 1

    print()
    print(
        "[QA] All required suites passed "
        "(or were intentionally skipped when non-required)."
    )
    return 0


def main():
    out_dir = os.environ.get("QA_OUT_DIR", ".qa/evidence")
    include_live_e2e = os.environ.get("QA_INCLUDE_LIVE_E2E", "0")
    return run_audit(out_dir, include_live_e2e)


if __name__ == "__main__":
    sys.exit(main())
