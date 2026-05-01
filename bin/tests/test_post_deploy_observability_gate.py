"""Tests for bin/post_deploy_observability_gate.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import post_deploy_observability_gate as gate  # noqa: E402


# ── build_checks ────────────────────────────────────────────────────────────


def test_build_checks_uses_window():
    checks = gate.build_checks(120)
    assert any("[120s]" in c.promql for c in checks)


def test_build_checks_has_all_critical_signals():
    names = [c.name for c in gate.build_checks(60)]
    assert "OOMKilled containers" in names
    assert "Deployments with unavailable replicas" in names
    assert "Containers in CrashLoopBackOff" in names


# ── query_prometheus ────────────────────────────────────────────────────────


def _mock_prom_response(value: float) -> bytes:
    return json.dumps(
        {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {}, "value": [1700000000, str(value)]}],
            },
        }
    ).encode()


def test_query_prometheus_parses_scalar():
    fake_resp = MagicMock()
    fake_resp.__enter__.return_value.read.return_value = _mock_prom_response(3.0)
    with patch.object(gate.urllib.request, "urlopen", return_value=fake_resp):
        v = gate.query_prometheus("http://prom", "vector(3)", 1.0)
    assert v == 3.0


def test_query_prometheus_empty_result_returns_zero():
    fake_resp = MagicMock()
    fake_resp.__enter__.return_value.read.return_value = json.dumps(
        {"status": "success", "data": {"resultType": "vector", "result": []}}
    ).encode()
    with patch.object(gate.urllib.request, "urlopen", return_value=fake_resp):
        v = gate.query_prometheus("http://prom", "vector(0)", 1.0)
    assert v == 0.0


def test_query_prometheus_raises_on_failure_status():
    fake_resp = MagicMock()
    fake_resp.__enter__.return_value.read.return_value = json.dumps(
        {"status": "error", "errorType": "bad_data", "error": "parse error"}
    ).encode()
    with patch.object(gate.urllib.request, "urlopen", return_value=fake_resp):
        try:
            gate.query_prometheus("http://prom", "garbage", 1.0)
        except RuntimeError as e:
            assert "Prometheus query failed" in str(e)
            return
    raise AssertionError("expected RuntimeError")


# ── evaluate ────────────────────────────────────────────────────────────────


def test_evaluate_all_zero_passes():
    checks = gate.build_checks(60)
    with patch.object(gate, "query_prometheus", return_value=0.0):
        code, summaries = gate.evaluate("http://prom", checks, 1.0)
    assert code == 0
    assert all(s["ok"] for s in summaries)


def test_evaluate_failing_severity_fails_build():
    checks = gate.build_checks(60)
    # First fail-severity check returns 2, others return 0.
    values = iter([2.0, 0.0, 0.0, 0.0])
    with patch.object(
        gate, "query_prometheus", side_effect=lambda *_args, **_k: next(values)
    ):
        code, _ = gate.evaluate("http://prom", checks, 1.0)
    assert code == 1


def test_evaluate_warn_severity_does_not_fail_build():
    # Only the 'warn' Pending-pods check is non-zero — should still pass.
    checks = gate.build_checks(60)
    pending_idx = next(i for i, c in enumerate(checks) if c.severity == "warn")
    values = [0.0] * len(checks)
    values[pending_idx] = 5.0
    iv = iter(values)
    with patch.object(
        gate, "query_prometheus", side_effect=lambda *_args, **_k: next(iv)
    ):
        code, summaries = gate.evaluate("http://prom", checks, 1.0)
    assert code == 0
    warn_result = next(s for s in summaries if s["severity"] == "warn")
    assert warn_result["ok"] is False


def test_evaluate_query_error_fails_build():
    checks = [gate.Check(name="x", promql="vector(0)", severity="fail")]
    with patch.object(gate, "query_prometheus", side_effect=RuntimeError("boom")):
        code, summaries = gate.evaluate("http://prom", checks, 1.0)
    assert code == 1
    assert summaries[0]["error"] == "boom"


# ── main ────────────────────────────────────────────────────────────────────


def test_main_returns_zero_when_quiet(monkeypatch):
    monkeypatch.setenv("OBSERVATION_WINDOW", "60")
    with patch.object(gate, "query_prometheus", return_value=0.0):
        assert gate.main([]) == 0


def test_main_returns_one_when_oom_present(monkeypatch):
    monkeypatch.setenv("OBSERVATION_WINDOW", "60")
    # First (OOM) check non-zero, others zero.
    values = iter([1.0, 0.0, 0.0, 0.0])
    with patch.object(
        gate, "query_prometheus", side_effect=lambda *_a, **_k: next(values)
    ):
        assert gate.main([]) == 1
