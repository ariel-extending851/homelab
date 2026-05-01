"""Tests for bin/infracost_diff_gate.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import infracost_diff_gate as gate  # noqa: E402


def _write_diff(tmp_path: Path, total: float, delta: float) -> Path:
    p = tmp_path / "diff.json"
    p.write_text(
        json.dumps(
            {
                "totalMonthlyCost": str(total),
                "diffTotalMonthlyCost": str(delta),
            }
        )
    )
    return p


def test_extract_delta_computes_baseline(tmp_path: Path) -> None:
    p = _write_diff(tmp_path, total=120.0, delta=20.0)
    base, pr, delta = gate.extract_delta(p)
    assert base == 100.0
    assert pr == 120.0
    assert delta == 20.0


def test_extract_delta_handles_missing_keys(tmp_path: Path) -> None:
    p = tmp_path / "diff.json"
    p.write_text("{}")
    base, pr, delta = gate.extract_delta(p)
    assert (base, pr, delta) == (0.0, 0.0, 0.0)


def test_under_threshold_passes(tmp_path: Path) -> None:
    p = _write_diff(tmp_path, total=110.0, delta=4.99)
    rc = gate.main(["--diff", str(p), "--max-delta", "5"])
    assert rc == 0


def test_over_threshold_fails(tmp_path: Path, capsys) -> None:
    p = _write_diff(tmp_path, total=110.0, delta=5.01)
    rc = gate.main(["--diff", str(p), "--max-delta", "5"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "exceeds threshold" in err
    assert "cost-approved" in err


def test_negative_delta_uses_absolute(tmp_path: Path) -> None:
    """A cost reduction of -10 still trips a $5 limit (refactors of cheap → expensive→cheap should be reviewed)."""
    p = _write_diff(tmp_path, total=90.0, delta=-10.0)
    rc = gate.main(["--diff", str(p), "--max-delta", "5"])
    assert rc == 1


def test_summary_file_appended(tmp_path: Path) -> None:
    p = _write_diff(tmp_path, total=110.0, delta=2.5)
    summary = tmp_path / "summary.md"
    summary.write_text("# pre-existing\n")
    rc = gate.main(
        [
            "--diff",
            str(p),
            "--max-delta",
            "5",
            "--summary",
            str(summary),
        ]
    )
    assert rc == 0
    body = summary.read_text()
    assert body.startswith("# pre-existing\n")
    assert "Infracost Gate" in body
    assert "+2.50" in body


def test_missing_diff_file(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "nope.json"
    rc = gate.main(["--diff", str(missing), "--max-delta", "5"])
    assert rc == 2
    assert "not found" in capsys.readouterr().err


def test_render_summary_marks_within_limit() -> None:
    out = gate.render_summary(100.0, 102.0, 2.0, 5.0, exceeded=False)
    assert "within limit" in out
    assert "+2.00" in out
    assert "100.00" in out


def test_render_summary_marks_over_limit() -> None:
    out = gate.render_summary(100.0, 110.0, 10.0, 5.0, exceeded=True)
    assert "OVER LIMIT" in out
    assert "+10.00" in out
