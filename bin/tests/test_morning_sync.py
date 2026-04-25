"""Tests for bin/morning_sync.py — pure parsers and summary logic."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import morning_sync  # noqa: E402
from morning_sync import (  # noqa: E402
    SyncResult,
    parse_kubectl_nodes,
    parse_tailscale_peers,
    print_summary,
)


# ── parse_kubectl_nodes ───────────────────────────────────────────────────────


def test_parse_kubectl_nodes_all_ready():
    stdout = (
        "server-0   Ready    control-plane   10d   v1.34.3+k3s1   10.0.0.1\n"
        "agent-rpi1 Ready    <none>           9d    v1.34.3+k3s1   10.0.0.2\n"
        "agent-rpi2 Ready    <none>           9d    v1.34.3+k3s1   10.0.0.3\n"
    )
    nodes = parse_kubectl_nodes(stdout)
    assert len(nodes) == 3
    assert all(status == "Ready" for _, status, _ in nodes)
    assert nodes[0] == ("server-0", "Ready", "control-plane")


def test_parse_kubectl_nodes_not_ready():
    stdout = (
        "server-0   Ready      control-plane  10d  v1.34.3+k3s1  10.0.0.1\n"
        "agent-rpi1 NotReady   <none>         9d   v1.34.3+k3s1  10.0.0.2\n"
    )
    nodes = parse_kubectl_nodes(stdout)
    not_ready = [name for name, status, _ in nodes if status != "Ready"]
    assert not_ready == ["agent-rpi1"]


def test_parse_kubectl_nodes_empty():
    assert parse_kubectl_nodes("") == []
    assert parse_kubectl_nodes(None) == []


def test_parse_kubectl_nodes_skips_short_lines():
    stdout = "server-0\n\nserver-1 Ready control-plane 10d v1.34.3+k3s1\n"
    nodes = parse_kubectl_nodes(stdout)
    # short line skipped, valid line kept
    assert len(nodes) == 1
    assert nodes[0][0] == "server-1"


# ── parse_tailscale_peers ─────────────────────────────────────────────────────


def _ts_json(peers):
    return json.dumps({"BackendState": "Running", "Peer": peers})


def test_parse_tailscale_peers_all_online():
    data = _ts_json(
        {
            "abc123": {"HostName": "server-0", "Online": True},
            "def456": {"HostName": "rpi1", "Online": True},
        }
    )
    peers = parse_tailscale_peers(data)
    assert len(peers) == 2
    assert all(online for _, online in peers)


def test_parse_tailscale_peers_one_offline():
    data = _ts_json(
        {
            "abc": {"HostName": "server-0", "Online": True},
            "def": {"HostName": "rpi1", "Online": False},
        }
    )
    peers = parse_tailscale_peers(data)
    online = [h for h, up in peers if up]
    offline = [h for h, up in peers if not up]
    assert online == ["server-0"]
    assert offline == ["rpi1"]


def test_parse_tailscale_peers_empty():
    assert parse_tailscale_peers("") == []
    assert parse_tailscale_peers(None) == []
    assert parse_tailscale_peers("not json") == []


def test_parse_tailscale_peers_no_peer_key():
    data = json.dumps({"BackendState": "Running"})
    assert parse_tailscale_peers(data) == []


def test_parse_tailscale_peers_uses_dnsname_fallback():
    data = _ts_json({"abc": {"DNSName": "mynode.ts.net", "Online": True}})
    peers = parse_tailscale_peers(data)
    assert peers == [("mynode.ts.net", True)]


# ── print_summary ─────────────────────────────────────────────────────────────


def _healthy_result():
    r = SyncResult()
    r.smoke_exit = 0
    r.smoke_failures = 0
    r.smoke_app_failures = 0
    r.ts_state = "Running"
    r.ts_peers_online = 2
    r.ts_peers_total = 2
    r.k3s_nodes = [("server-0", "Ready", "control-plane"), ("rpi1", "Ready", "<none>")]
    r.k3s_not_ready = []
    r.loki_error_count = 0
    r.loki_fatal_count = 0
    return r


def test_summary_all_healthy_exits_0(capsys):
    code = print_summary(_healthy_result())
    assert code == 0
    out = capsys.readouterr().out
    assert "✓  Cluster" in out
    assert "✓  Network" in out
    assert "✓  Logs" in out


def test_summary_smoke_failed_exits_1(capsys):
    r = _healthy_result()
    r.smoke_exit = 1
    r.smoke_failures = 3
    code = print_summary(r)
    assert code == 1
    assert "✗  Cluster" in capsys.readouterr().out


def test_summary_minor_app_issues_exits_2(capsys):
    r = _healthy_result()
    r.smoke_exit = 2
    r.smoke_app_failures = 2
    code = print_summary(r)
    assert code == 2
    assert "⚠  Cluster" in capsys.readouterr().out


def test_summary_k3s_not_ready_exits_1(capsys):
    r = _healthy_result()
    r.k3s_not_ready = ["rpi1"]
    code = print_summary(r)
    assert code == 1
    out = capsys.readouterr().out
    assert "rpi1" in out


def test_summary_ts_peer_offline_exits_2(capsys):
    r = _healthy_result()
    r.ts_peers_online = 1
    r.ts_peers_total = 2
    code = print_summary(r)
    assert code == 2
    assert "⚠  Network" in capsys.readouterr().out


def test_summary_loki_errors_exits_2(capsys):
    r = _healthy_result()
    r.loki_error_count = 3
    r.loki_fatal_count = 1
    code = print_summary(r)
    assert code == 2
    assert "⚠  Logs" in capsys.readouterr().out


def test_summary_loki_unreachable_exits_0_with_warning(capsys):
    r = _healthy_result()
    r.loki_error = "kubectl logs failed"
    code = print_summary(r)
    # Loki unreachable is a warning but not critical on its own
    assert code == 0
    assert "⚠  Logs" in capsys.readouterr().out


def test_summary_three_bullets_always_printed(capsys):
    print_summary(_healthy_result())
    out = capsys.readouterr().out
    bullets = [ln for ln in out.splitlines() if ln.strip().startswith("•")]
    assert len(bullets) == 3


# ── check_tailscale integration (mocked subprocess) ──────────────────────────


def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_check_tailscale_running(capsys):
    ts_json = _ts_json(
        {
            "abc": {"HostName": "server-0", "Online": True},
            "def": {"HostName": "rpi1", "Online": False},
        }
    )
    result = SyncResult()
    with patch("subprocess.run", return_value=_proc(0, ts_json)):
        morning_sync.check_tailscale(result)
    assert result.ts_state == "Running"
    assert result.ts_peers_online == 1
    assert result.ts_peers_total == 2
    out = capsys.readouterr().out
    assert "Running" in out


def test_check_tailscale_cli_missing(capsys):
    result = SyncResult()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        morning_sync.check_tailscale(result)
    assert "not found" in result.ts_error
    assert "✗" in capsys.readouterr().out


# ── check_k3s_nodes integration (mocked subprocess) ──────────────────────────


def test_check_k3s_nodes_all_ready(capsys):
    stdout = (
        "server-0   Ready   control-plane   10d  v1.34.3+k3s1  10.0.0.1\n"
        "rpi1       Ready   <none>           9d   v1.34.3+k3s1  10.0.0.2\n"
    )
    result = SyncResult()
    with patch("subprocess.run", return_value=_proc(0, stdout)):
        morning_sync.check_k3s_nodes("/fake/kubeconfig", result)
    assert result.k3s_not_ready == []
    assert len(result.k3s_nodes) == 2
    assert "All 2 node(s) Ready" in capsys.readouterr().out


def test_check_k3s_nodes_not_ready(capsys):
    stdout = (
        "server-0  Ready     control-plane  10d  v1.34.3\n"
        "rpi1      NotReady  <none>          9d   v1.34.3\n"
    )
    result = SyncResult()
    with patch("subprocess.run", return_value=_proc(0, stdout)):
        morning_sync.check_k3s_nodes("/fake/kubeconfig", result)
    assert result.k3s_not_ready == ["rpi1"]
    assert "NOT Ready" in capsys.readouterr().out


# ── check_loki_logs integration (mocked subprocess) ──────────────────────────


def test_check_loki_logs_clean(capsys):
    logs = "level=info msg=ingester started\nlevel=info msg=querier ready\n"
    result = SyncResult()
    with patch("subprocess.run", return_value=_proc(0, logs)):
        morning_sync.check_loki_logs("/fake/kubeconfig", result)
    assert result.loki_error_count == 0
    assert result.loki_fatal_count == 0
    assert "No ERROR" in capsys.readouterr().out


def test_check_loki_logs_with_errors(capsys):
    logs = (
        "level=info msg=ok\n"
        "level=ERROR msg=compactor failed\n"
        "level=FATAL msg=wal corrupted\n"
        "level=ERROR msg=ring unhealthy\n"
    )
    result = SyncResult()
    with patch("subprocess.run", return_value=_proc(0, logs)):
        morning_sync.check_loki_logs("/fake/kubeconfig", result)
    assert result.loki_error_count == 2
    assert result.loki_fatal_count == 1
    out = capsys.readouterr().out
    assert "2 ERROR" in out
    assert "1 FATAL" in out
