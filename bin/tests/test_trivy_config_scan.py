"""Unit tests for bin/trivy_config_scan.py — closes the only source-coverage hole.

Tests focus on the pure-Python report parsing and decision logic. The
`run_trivy_config` shell-out is exercised through monkeypatching so the
suite stays hermetic — we don't want CI to depend on a trivy binary just
to validate aggregation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bin import trivy_config_scan as tcs


# ── summarize() ─────────────────────────────────────────────────────────


def test_summarize_empty_report() -> None:
    out = tcs.summarize({})
    assert out == {"counts": {"HIGH": 0, "CRITICAL": 0}, "findings": []}


def test_summarize_counts_only_blocking_severities() -> None:
    """LOW/MEDIUM/UNKNOWN must be ignored — only HIGH+CRITICAL block."""
    report = {
        "Results": [
            {
                "Target": "k8s/apps/foo/deploy.yaml",
                "Misconfigurations": [
                    {"ID": "AVD-001", "Severity": "HIGH", "Title": "h1"},
                    {"ID": "AVD-002", "Severity": "LOW", "Title": "low"},
                    {"ID": "AVD-003", "Severity": "CRITICAL", "Title": "crit"},
                    {"ID": "AVD-004", "Severity": "MEDIUM", "Title": "med"},
                ],
            }
        ]
    }
    summary = tcs.summarize(report)
    assert summary["counts"] == {"HIGH": 1, "CRITICAL": 1}
    assert len(summary["findings"]) == 2
    severities = {f["severity"] for f in summary["findings"]}
    assert severities == {"HIGH", "CRITICAL"}


def test_summarize_uses_avdid_when_id_missing() -> None:
    report = {
        "Results": [
            {
                "Target": "x.yaml",
                "Misconfigurations": [
                    {"AVDID": "AVD-FALL-001", "Severity": "HIGH", "Title": "t"}
                ],
            }
        ]
    }
    finding = tcs.summarize(report)["findings"][0]
    assert finding["id"] == "AVD-FALL-001"


def test_summarize_handles_missing_misconfigurations_key() -> None:
    """Some Results entries have no Misconfigurations list at all."""
    report = {"Results": [{"Target": "t.yaml"}]}
    assert tcs.summarize(report)["counts"] == {"HIGH": 0, "CRITICAL": 0}


# ── has_blocking() ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "counts,expected",
    [
        ({"HIGH": 0, "CRITICAL": 0}, False),
        ({"HIGH": 1, "CRITICAL": 0}, True),
        ({"HIGH": 0, "CRITICAL": 1}, True),
        ({"HIGH": 5, "CRITICAL": 5}, True),
    ],
)
def test_has_blocking(counts: dict, expected: bool) -> None:
    assert tcs.has_blocking({"counts": counts}) is expected


# ── main() integration with monkeypatched trivy ─────────────────────────


def test_main_advisory_mode_returns_zero_on_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Advisory mode (default): report findings but exit 0 so CI keeps moving."""
    fake_report = {
        "Results": [
            {
                "Target": "k8s/foo.yaml",
                "Misconfigurations": [
                    {"ID": "AVD-X", "Severity": "CRITICAL", "Title": "bad"}
                ],
            }
        ]
    }

    def fake_run(path, output_path, ignorefile):  # type: ignore[no-untyped-def]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(fake_report))
        return fake_report

    monkeypatch.setattr(tcs, "run_trivy_config", fake_run)
    monkeypatch.chdir(tmp_path)
    Path(tmp_path / "k8s").mkdir()

    rc = tcs.main(["--paths", "k8s", "--output-dir", str(tmp_path / ".qa/trivy")])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Advisory mode" in captured.out
    assert "CRITICAL=1" in captured.out


def test_main_strict_mode_returns_one_on_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = {
        "Results": [
            {
                "Target": "k8s/foo.yaml",
                "Misconfigurations": [
                    {"ID": "AVD-X", "Severity": "HIGH", "Title": "bad"}
                ],
            }
        ]
    }

    def fake_run(path, output_path, ignorefile):  # type: ignore[no-untyped-def]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(fake_report))
        return fake_report

    monkeypatch.setattr(tcs, "run_trivy_config", fake_run)
    monkeypatch.chdir(tmp_path)
    Path(tmp_path / "k8s").mkdir()

    rc = tcs.main(
        ["--paths", "k8s", "--output-dir", str(tmp_path / ".qa/trivy"), "--strict"]
    )
    assert rc == 1


def test_main_clean_paths_return_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(path, output_path, ignorefile):  # type: ignore[no-untyped-def]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}")
        return {}

    monkeypatch.setattr(tcs, "run_trivy_config", fake_run)
    monkeypatch.chdir(tmp_path)
    Path(tmp_path / "k8s").mkdir()
    Path(tmp_path / "infra/aws").mkdir(parents=True)

    rc = tcs.main(["--output-dir", str(tmp_path / ".qa/trivy")])
    assert rc == 0


def test_main_skips_missing_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """--paths with a non-existent directory must skip with a warning.

    Pairs the missing path with one that exists so the aggregate summary
    can be written — exercising the "skip + still produce report" path
    rather than the "every path missing" edge case.
    """
    out_dir = tmp_path / ".qa/trivy"

    def fake_run(path, output_path, ignorefile):  # type: ignore[no-untyped-def]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}")
        return {}

    monkeypatch.setattr(tcs, "run_trivy_config", fake_run)
    monkeypatch.chdir(tmp_path)
    Path(tmp_path / "k8s").mkdir()

    rc = tcs.main(["--paths", "does-not-exist", "k8s", "--output-dir", str(out_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Skipping missing path" in out
    assert "does-not-exist" in out


def test_main_aggregate_summary_written_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(path, output_path, ignorefile):  # type: ignore[no-untyped-def]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("{}")
        return {}

    monkeypatch.setattr(tcs, "run_trivy_config", fake_run)
    monkeypatch.chdir(tmp_path)
    Path(tmp_path / "k8s").mkdir()
    out_dir = tmp_path / ".qa/trivy"

    tcs.main(["--paths", "k8s", "--output-dir", str(out_dir)])
    summary_path = out_dir / "config-summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())
    assert summary["totals"] == {"HIGH": 0, "CRITICAL": 0}
    assert "k8s" in summary["paths"]
