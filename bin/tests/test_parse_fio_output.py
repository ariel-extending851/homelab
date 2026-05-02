"""Tests for bin/parse_fio_output.py — fio JSON → log line + threshold gate.

The parser is the seam between an external tool (fio) and our observability
contract: it converts a fio job-result JSON document into a structured log
line that Loki can index, and exits non-zero if measured latency breaches
the SLA threshold (default p99 <= 50ms on RPi4 SD/USB media).

Tests cover:
  - happy-path JSON parsing across read+write modes
  - missing/malformed input
  - threshold gating (exit code 0 vs 1)
  - the structured JSON log line shape (Loki-stable schema)
"""

from __future__ import annotations

import io
import json

import pytest

from bin import parse_fio_output as pfo


# ── helpers ─────────────────────────────────────────────────────────────


def _fio_job(p99_write_ns: int = 5_000_000, p99_read_ns: int = 4_000_000) -> dict:
    """Build a minimal fio JSON document with the latency fields we read."""
    return {
        "jobs": [
            {
                "jobname": "homelab-storage-latency",
                "write": {
                    "iops": 250.5,
                    "bw": 1024,
                    "clat_ns": {
                        "mean": 2_000_000,
                        "stddev": 500_000,
                        "percentile": {"99.000000": p99_write_ns},
                    },
                },
                "read": {
                    "iops": 380.0,
                    "bw": 2048,
                    "clat_ns": {
                        "mean": 1_500_000,
                        "stddev": 300_000,
                        "percentile": {"99.000000": p99_read_ns},
                    },
                },
            }
        ]
    }


# ── parse_fio_json() ────────────────────────────────────────────────────


def test_parse_fio_json_extracts_p99_in_milliseconds():
    """fio reports nanoseconds; we surface p99 as ms (Prometheus convention)."""
    raw = json.dumps(_fio_job(p99_write_ns=12_000_000, p99_read_ns=8_000_000))
    parsed = pfo.parse_fio_json(raw)
    assert parsed["p99_write_ms"] == 12.0
    assert parsed["p99_read_ms"] == 8.0


def test_parse_fio_json_includes_iops_and_bandwidth():
    """Operators want IOPS/BW alongside latency to debug SD-card aging."""
    raw = json.dumps(_fio_job())
    parsed = pfo.parse_fio_json(raw)
    assert parsed["write_iops"] == 250.5
    assert parsed["read_iops"] == 380.0
    assert parsed["write_bw_kbs"] == 1024
    assert parsed["read_bw_kbs"] == 2048


def test_parse_fio_json_invalid_returns_empty():
    """Garbage input → empty dict; caller decides whether to fail or skip."""
    assert pfo.parse_fio_json("") == {}
    assert pfo.parse_fio_json("not-json") == {}
    assert pfo.parse_fio_json("{}") == {}
    assert pfo.parse_fio_json('{"jobs": []}') == {}


def test_parse_fio_json_missing_percentile_section():
    """Older fio versions emit a different percentile key — be defensive."""
    doc = _fio_job()
    del doc["jobs"][0]["write"]["clat_ns"]["percentile"]
    parsed = pfo.parse_fio_json(json.dumps(doc))
    # Missing percentile → field absent; read side still populated.
    assert "p99_write_ms" not in parsed
    assert parsed["p99_read_ms"] == 4.0


# ── threshold gating ────────────────────────────────────────────────────


def test_breaches_threshold_under_limit():
    metrics = {"p99_write_ms": 10.0, "p99_read_ms": 5.0}
    assert pfo.breaches_threshold(metrics, threshold_ms=50.0) is False


def test_breaches_threshold_write_over_limit():
    metrics = {"p99_write_ms": 75.0, "p99_read_ms": 5.0}
    assert pfo.breaches_threshold(metrics, threshold_ms=50.0) is True


def test_breaches_threshold_read_over_limit():
    metrics = {"p99_write_ms": 10.0, "p99_read_ms": 80.0}
    assert pfo.breaches_threshold(metrics, threshold_ms=50.0) is True


def test_breaches_threshold_missing_metrics_is_not_a_breach():
    """If parsing failed and we have no metric, don't fail-loud — fail-quiet
    is the right call: a noisy false-positive blinds operators to real ones."""
    assert pfo.breaches_threshold({}, threshold_ms=50.0) is False


# ── render_log_line() ───────────────────────────────────────────────────


def test_render_log_line_emits_stable_schema():
    """Loki indexes by JSON keys; the schema must stay backwards-compatible."""
    metrics = {
        "p99_write_ms": 12.3,
        "p99_read_ms": 8.1,
        "write_iops": 250.5,
        "read_iops": 380.0,
        "write_bw_kbs": 1024,
        "read_bw_kbs": 2048,
    }
    line = pfo.render_log_line(metrics, host="rasp-pi-04", threshold_ms=50.0)
    obj = json.loads(line)
    # Required schema fields:
    assert obj["event"] == "storage_latency"
    assert obj["host"] == "rasp-pi-04"
    assert obj["threshold_ms"] == 50.0
    assert obj["p99_write_ms"] == 12.3
    assert obj["p99_read_ms"] == 8.1
    assert obj["breach"] is False  # under threshold
    assert "timestamp" in obj  # ISO-8601, set by render


def test_render_log_line_marks_breach_when_threshold_exceeded():
    metrics = {"p99_write_ms": 75.0, "p99_read_ms": 8.0}
    line = pfo.render_log_line(metrics, host="rasp-pi-04", threshold_ms=50.0)
    obj = json.loads(line)
    assert obj["breach"] is True


# ── main() integration ─────────────────────────────────────────────────


def test_main_pass_under_threshold(capsys, tmp_path):
    fio_path = tmp_path / "fio.json"
    fio_path.write_text(json.dumps(_fio_job(p99_write_ns=10_000_000)))
    rc = pfo.main(["--input", str(fio_path), "--threshold-ms", "50", "--host", "rpi4"])
    assert rc == 0
    line = capsys.readouterr().out.strip()
    obj = json.loads(line)
    assert obj["breach"] is False
    assert obj["p99_write_ms"] == 10.0


def test_main_fail_over_threshold(capsys, tmp_path):
    fio_path = tmp_path / "fio.json"
    fio_path.write_text(json.dumps(_fio_job(p99_write_ns=80_000_000)))
    rc = pfo.main(["--input", str(fio_path), "--threshold-ms", "50", "--host", "rpi4"])
    assert rc == 1
    line = capsys.readouterr().out.strip()
    obj = json.loads(line)
    assert obj["breach"] is True
    assert obj["p99_write_ms"] == 80.0


def test_main_reads_stdin_when_no_input_arg(capsys, monkeypatch):
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps(_fio_job(p99_write_ns=5_000_000)))
    )
    rc = pfo.main(["--threshold-ms", "50", "--host", "rpi4"])
    assert rc == 0
    obj = json.loads(capsys.readouterr().out.strip())
    assert obj["p99_write_ms"] == 5.0


def test_main_empty_input_returns_2_for_distinct_failure(capsys):
    """rc=2 → exec problem (no fio data); rc=1 → SLA breach. Operators
    should be able to tell the two apart in alerting."""
    import io as _io
    import sys

    stdin_orig = sys.stdin
    sys.stdin = _io.StringIO("")
    try:
        rc = pfo.main(["--threshold-ms", "50", "--host", "rpi4"])
    finally:
        sys.stdin = stdin_orig
    assert rc == 2
