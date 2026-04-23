"""Tests for bin/qa_scorecard.py"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import qa_scorecard as qs  # noqa: E402


# ── load_audit_files ─────────────────────────────────────────────────────────


def test_load_audit_files_empty_dir_returns_empty(tmp_path):
    assert qs.load_audit_files(tmp_path) == []


def test_load_audit_files_skips_invalid_json(tmp_path):
    (tmp_path / "qa-audit-bad.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "qa-audit-good.json").write_text(
        json.dumps({"results": []}), encoding="utf-8"
    )
    loaded = qs.load_audit_files(tmp_path)
    assert len(loaded) == 1
    assert loaded[0][0].name == "qa-audit-good.json"


def test_load_audit_files_sorts_by_name(tmp_path):
    for name in ("qa-audit-c.json", "qa-audit-a.json", "qa-audit-b.json"):
        (tmp_path / name).write_text(json.dumps({}), encoding="utf-8")
    loaded = qs.load_audit_files(tmp_path)
    assert [p.name for p, _ in loaded] == [
        "qa-audit-a.json",
        "qa-audit-b.json",
        "qa-audit-c.json",
    ]


# ── parse_timestamp ──────────────────────────────────────────────────────────


def test_parse_timestamp_uses_audit_value_when_present():
    assert qs.parse_timestamp({"timestamp_utc": "2026-04-22T00:00:00Z"}, "fb") == (
        "2026-04-22T00:00:00Z"
    )


def test_parse_timestamp_falls_back_when_missing():
    assert qs.parse_timestamp({}, "fallback") == "fallback"


def test_parse_timestamp_falls_back_when_empty_string():
    assert qs.parse_timestamp({"timestamp_utc": "   "}, "fb") == "fb"


# ── compute_run_metrics ──────────────────────────────────────────────────────


def test_compute_run_metrics_mixed_pass_fail_skip():
    audit = {
        "results": [
            {
                "suite": "a",
                "required": "yes",
                "status": "passed",
                "duration_seconds": 10,
            },
            {
                "suite": "b",
                "required": "yes",
                "status": "failed",
                "duration_seconds": 5,
            },
            {
                "suite": "c",
                "required": "yes",
                "status": "skipped",
                "skip_reason": "OFFLINE",
                "duration_seconds": 2,
            },
            {"suite": "d", "required": "no", "status": "passed", "duration_seconds": 3},
        ]
    }
    m = qs.compute_run_metrics(audit)
    assert m["required_total"] == 3
    assert m["required_passed"] == 1
    assert m["required_failed"] == 1
    assert m["required_skipped"] == 1
    assert m["required_pass_rate"] == round(100 / 3, 2)
    assert m["total_duration_seconds"] == 20
    assert m["required_skip_details"] == [{"suite": "c", "reason": "OFFLINE"}]


def test_compute_run_metrics_empty_results_no_divzero():
    m = qs.compute_run_metrics({"results": []})
    assert m["required_pass_rate"] == 0.0
    assert m["required_skip_rate"] == 0.0
    assert m["required_total"] == 0


def test_compute_run_metrics_skip_without_reason_defaults_to_placeholder():
    audit = {"results": [{"suite": "x", "required": "yes", "status": "skipped"}]}
    m = qs.compute_run_metrics(audit)
    assert m["required_skip_details"] == [{"suite": "x", "reason": "NO_REASON_CODE"}]


# ── compute_flake_rate ───────────────────────────────────────────────────────


def test_compute_flake_rate_empty_returns_zero():
    assert qs.compute_flake_rate([]) == 0.0


def test_compute_flake_rate_detects_flaky_suite():
    recent = [
        {"results": [{"suite": "a", "required": "yes", "status": "passed"}]},
        {"results": [{"suite": "a", "required": "yes", "status": "failed"}]},
    ]
    assert qs.compute_flake_rate(recent) == 100.0


def test_compute_flake_rate_stable_suite_is_not_flaky():
    recent = [
        {"results": [{"suite": "a", "required": "yes", "status": "passed"}]},
        {"results": [{"suite": "a", "required": "yes", "status": "passed"}]},
    ]
    assert qs.compute_flake_rate(recent) == 0.0


def test_compute_flake_rate_skips_non_required_and_empty_suite():
    """Covers lines 85 (non-required continue) and 88 (empty-suite continue)."""
    recent = [
        {
            "results": [
                {"suite": "a", "required": "no", "status": "passed"},  # skipped at L85
                {"suite": "", "required": "yes", "status": "passed"},  # skipped at L88
            ]
        }
    ]
    assert qs.compute_flake_rate(recent) == 0.0


# ── compute_suite_flake_details ──────────────────────────────────────────────


def test_compute_suite_flake_details_includes_performance_even_without_required():
    recent = [
        {"results": [{"suite": "performance", "required": "no", "status": "passed"}]},
        {"results": [{"suite": "performance", "required": "no", "status": "failed"}]},
    ]
    details = qs.compute_suite_flake_details(recent)
    assert len(details) == 1
    row = details[0]
    assert row["suite"] == "performance"
    assert row["is_flaky"] is True
    assert row["runs"] == 2


def test_compute_suite_flake_details_skips_non_required_and_empty_suite():
    """Covers lines 117 (non-required/non-perf continue) and 120 (empty-suite continue)."""
    recent = [
        {
            "results": [
                {
                    "suite": "other",
                    "required": "no",
                    "status": "passed",
                },  # skipped L117
                {"suite": "", "required": "yes", "status": "passed"},  # skipped L120
            ]
        }
    ]
    assert qs.compute_suite_flake_details(recent) == []


def test_compute_budget_violations_skips_empty_suite():
    """Covers line 176 (empty-suite continue)."""
    results = [{"suite": "", "duration_seconds": 99999}]
    assert qs.compute_budget_violations(results, {}, margin_percent=20) == []


def test_compute_suite_flake_details_counts_runs_once_per_run():
    recent = [
        {
            "results": [
                {"suite": "a", "required": "yes", "status": "passed"},
                {"suite": "a", "required": "yes", "status": "passed"},
            ]
        },
        {"results": [{"suite": "a", "required": "yes", "status": "passed"}]},
    ]
    details = qs.compute_suite_flake_details(recent)
    assert details[0]["runs"] == 2


# ── load_budget_file ─────────────────────────────────────────────────────────


def test_load_budget_file_missing_returns_empty(tmp_path):
    assert qs.load_budget_file(tmp_path / "nope.json") == {}


def test_load_budget_file_invalid_json_returns_empty(tmp_path):
    f = tmp_path / "b.json"
    f.write_text("not-json", encoding="utf-8")
    assert qs.load_budget_file(f) == {}


def test_load_budget_file_skips_non_integer_values(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"a": 30, "b": "oops", "c": 60}), encoding="utf-8")
    assert qs.load_budget_file(f) == {"a": 30, "c": 60}


# ── compute_budget_violations ────────────────────────────────────────────────


def test_compute_budget_violations_under_budget_has_no_violation():
    results = [{"suite": "shell", "duration_seconds": 30}]
    violations = qs.compute_budget_violations(results, {}, margin_percent=20)
    assert violations == []


def test_compute_budget_violations_over_budget_includes_margin():
    # shell default budget is 90s, margin 20% → allowed 108
    results = [{"suite": "shell", "duration_seconds": 200}]
    violations = qs.compute_budget_violations(results, {}, margin_percent=20)
    assert len(violations) == 1
    v = violations[0]
    assert v["suite"] == "shell"
    assert v["observed_seconds"] == 200
    assert v["allowed_seconds"] == 108
    assert v["threshold_seconds"] == 90


def test_compute_budget_violations_uses_override():
    results = [{"suite": "shell", "duration_seconds": 50}]
    # override shell to 40; margin 0 → allowed 40; observed 50 > 40 → violation
    violations = qs.compute_budget_violations(results, {"shell": 40}, margin_percent=0)
    assert violations[0]["threshold_seconds"] == 40


def test_compute_budget_violations_skips_suite_without_budget():
    results = [{"suite": "unknown_suite", "duration_seconds": 99999}]
    assert qs.compute_budget_violations(results, {}, margin_percent=20) == []


# ── verify_no_required_skips / verify_duration_budgets ───────────────────────


def test_verify_no_required_skips_zero_returns_0(capsys):
    rc = qs.verify_no_required_skips(
        {"required_skipped": 0, "required_skip_details": []}
    )
    assert rc == 0
    assert "[OK]" in capsys.readouterr().out


def test_verify_no_required_skips_nonzero_returns_1(capsys):
    metrics = {
        "required_skipped": 2,
        "required_skip_details": [
            {"suite": "a", "reason": "R1"},
            {"suite": "b", "reason": "R2"},
        ],
    }
    rc = qs.verify_no_required_skips(metrics)
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "a: R1" in out
    assert "b: R2" in out


def test_verify_duration_budgets_empty_returns_0(capsys):
    assert qs.verify_duration_budgets([]) == 0
    assert "[OK]" in capsys.readouterr().out


def test_verify_duration_budgets_with_violations_returns_1(capsys):
    violations = [
        {
            "suite": "shell",
            "observed_seconds": 200,
            "allowed_seconds": 108,
            "threshold_seconds": 90,
        }
    ]
    rc = qs.verify_duration_budgets(violations)
    assert rc == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "shell" in out


# ── build_markdown (smoke) ───────────────────────────────────────────────────


def test_build_markdown_includes_core_sections():
    scorecard = {
        "generated_utc": "2026-04-22T00:00:00Z",
        "history_limit": 14,
        "duration_budget_margin_percent": 20,
        "flake_rate_percent": 0.0,
        "flake_by_suite": [
            {
                "suite": "shell",
                "runs": 1,
                "passed": True,
                "failed": False,
                "skipped": False,
                "is_flaky": False,
            }
        ],
        "latest_run": {
            "audit_file": "qa-audit-x.json",
            "timestamp_utc": "2026-04-22T00:00:00Z",
            "metrics": {
                "required_pass_rate": 100.0,
                "required_skip_rate": 0.0,
                "required_total": 1,
                "required_passed": 1,
                "required_failed": 0,
                "required_skipped": 0,
                "total_duration_seconds": 10,
                "required_skip_details": [{"suite": "a", "reason": "R"}],
            },
            "duration_budget_violations": [
                {
                    "suite": "shell",
                    "observed_seconds": 200,
                    "allowed_seconds": 108,
                    "threshold_seconds": 90,
                }
            ],
        },
        "history": [
            {
                "audit_file": "qa-audit-x.json",
                "timestamp_utc": "2026-04-22T00:00:00Z",
                "metrics": {
                    "required_pass_rate": 100.0,
                    "required_skip_rate": 0.0,
                    "required_failed": 0,
                    "total_duration_seconds": 10,
                },
            }
        ],
    }
    md = qs.build_markdown(scorecard)
    assert "# QA Scorecard" in md
    assert "## Latest Metrics" in md
    assert "## Flake Details" in md
    assert "## Required Skips" in md
    assert "## Duration Budget Violations" in md


# ── main (integration) ───────────────────────────────────────────────────────


def _write_audit(
    path: Path, *, suite="shell", status="passed", duration=10, required="yes"
):
    audit = {
        "timestamp_utc": "2026-04-22T00:00:00Z",
        "results": [
            {
                "suite": suite,
                "required": required,
                "status": status,
                "duration_seconds": duration,
            }
        ],
    }
    path.write_text(json.dumps(audit), encoding="utf-8")


def test_main_no_audits_returns_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["qa_scorecard", "--input-dir", str(tmp_path)])
    rc = qs.main()
    assert rc == 1
    assert "No audit files" in capsys.readouterr().out


def test_main_happy_path_writes_four_artifacts(tmp_path, monkeypatch):
    _write_audit(tmp_path / "qa-audit-20260422.json")
    monkeypatch.setattr(sys, "argv", ["qa_scorecard", "--input-dir", str(tmp_path)])
    rc = qs.main()
    assert rc == 0
    assert (tmp_path / "qa-scorecard-latest.json").exists()
    assert (tmp_path / "qa-scorecard-latest.md").exists()
    timestamped_json = list(tmp_path.glob("qa-scorecard-*.json"))
    timestamped_md = list(tmp_path.glob("qa-scorecard-*.md"))
    # latest + timestamped
    assert len(timestamped_json) == 2
    assert len(timestamped_md) == 2


def test_main_verify_no_required_skips_fails_when_skip_present(tmp_path, monkeypatch):
    _write_audit(tmp_path / "qa-audit-1.json", status="skipped")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qa_scorecard",
            "--input-dir",
            str(tmp_path),
            "--verify-no-required-skips",
        ],
    )
    assert qs.main() == 1


def test_main_verify_duration_budgets_fails_on_violation(tmp_path, monkeypatch):
    # shell default budget 90, margin 20 → allowed 108; 500 > 108
    _write_audit(tmp_path / "qa-audit-1.json", suite="shell", duration=500)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qa_scorecard",
            "--input-dir",
            str(tmp_path),
            "--verify-duration-budgets",
        ],
    )
    assert qs.main() == 1


def test_main_verify_flags_both_pass_on_clean_run(tmp_path, monkeypatch):
    _write_audit(tmp_path / "qa-audit-1.json", suite="shell", duration=10)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qa_scorecard",
            "--input-dir",
            str(tmp_path),
            "--verify-no-required-skips",
            "--verify-duration-budgets",
        ],
    )
    assert qs.main() == 0
