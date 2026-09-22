"""Unit tests for bin/test_network.py.

Verifies mathematical calculations, DNS packet encoders/decoders,
bufferbloat grading, and report generators with 100% offline isolation.
"""

import json
import math
from unittest.mock import patch

from bin.test_network import (
    AuditResult,
    LatencyStats,
    build_dns_query,
    calculate_stats,
    classify_bufferbloat,
    is_domain_blocked,
    parse_dns_a_record,
    print_json_report,
    print_terminal_report,
)


def test_is_domain_blocked():
    assert is_domain_blocked([]) is True  # NXDOMAIN
    assert is_domain_blocked(["0.0.0.0"]) is True  # Cloudflare Family sinkhole
    assert is_domain_blocked(["94.140.14.35"]) is True  # AdGuard Family sinkhole
    assert is_domain_blocked(["185.228.168.10"]) is True  # CleanBrowsing Family sinkhole
    assert is_domain_blocked(["142.250.190.46"]) is False  # Public legitimate IP


# ── Statistical & Math Tests ───────────────────────────────────────────────


def test_calculate_stats_empty():
    stats = calculate_stats([])
    assert stats == LatencyStats(0.0, 0.0, 0.0, 0.0, 100.0, 0)


def test_calculate_stats_all_none():
    stats = calculate_stats([None, None, None])
    assert stats.loss_pct == 100.0
    assert stats.samples_count == 0


def test_calculate_stats_single_sample():
    stats = calculate_stats([5.5])
    assert stats.min_ms == 5.5
    assert stats.avg_ms == 5.5
    assert stats.max_ms == 5.5
    assert stats.jitter_ms == 0.0
    assert stats.loss_pct == 0.0
    assert stats.samples_count == 1


def test_calculate_stats_multiple_samples():
    samples = [10.0, 12.0, 14.0, None]
    stats = calculate_stats(samples)
    assert stats.min_ms == 10.0
    assert stats.avg_ms == 12.0
    assert stats.max_ms == 14.0
    # Variance: ((10-12)^2 + (12-12)^2 + (14-12)^2) / (3-1) = 8 / 2 = 4 -> stdev = 2.0
    assert math.isclose(stats.jitter_ms, 2.0)
    assert stats.loss_pct == 25.0
    assert stats.samples_count == 3


def test_classify_bufferbloat_grades():
    assert classify_bufferbloat(10.0, 12.0) == ("A+", 2.0)
    assert classify_bufferbloat(10.0, 20.0) == ("A", 10.0)
    assert classify_bufferbloat(10.0, 35.0) == ("B", 25.0)
    assert classify_bufferbloat(10.0, 60.0) == ("C", 50.0)
    assert classify_bufferbloat(10.0, 100.0) == ("D", 90.0)
    # Loaded faster than idle (jitter anomaly)
    assert classify_bufferbloat(15.0, 12.0) == ("A+", 0.0)


# ── DNS Packet Builder & Parser Tests ──────────────────────────────────────


def test_build_dns_query_format():
    query = build_dns_query("example.com", transaction_id=0xABCD)
    assert query[:2] == b"\xAB\xCD"  # ID
    assert query[2:4] == b"\x01\x00"  # Standard query flags
    assert query[4:6] == b"\x00\x01"  # QDCOUNT = 1
    # Domain format: \x07example\x03com\x00
    assert b"\x07example\x03com\x00" in query
    # Footer: QTYPE=1 (A), QCLASS=1 (IN)
    assert query.endswith(b"\x00\x01\x00\x01")


def test_parse_dns_a_record_empty_or_truncated():
    assert parse_dns_a_record(b"") == []
    assert parse_dns_a_record(b"\x00" * 10) == []


def test_parse_dns_a_record_nonzero_rcode():
    # Header with RCODE = 3 (NXDOMAIN)
    header = b"\x12\x34\x81\x83\x00\x01\x00\x00\x00\x00\x00\x00"
    assert parse_dns_a_record(header) == []


def test_parse_dns_a_record_valid_ipv4():
    # Build a simulated DNS response for "test.local" -> 192.168.8.1
    # Header: ID 0x1234, Flags 0x8180 (No error), QDCOUNT=1, ANCOUNT=1, NSCOUNT=0, ARCOUNT=0
    header = b"\x12\x34\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
    question = b"\x04test\x05local\x00\x00\x01\x00\x01"
    # Answer: Name pointer 0xC00C, TYPE=1, CLASS=1, TTL=60, RDLENGTH=4, RDATA=192.168.8.1
    answer = (
        b"\xC0\x0C"
        b"\x00\x01"
        b"\x00\x01"
        b"\x00\x00\x00\x3C"
        b"\x00\x04"
        + bytes([192, 168, 8, 1])
    )
    packet = header + question + answer
    ips = parse_dns_a_record(packet)
    assert ips == ["192.168.8.1"]


def test_parse_dns_a_record_sinkhole_zero():
    # Test 0.0.0.0 sinkhole response
    header = b"\x12\x34\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
    question = b"\x07malware\x00\x00\x01\x00\x01"
    answer = (
        b"\xC0\x0C"
        b"\x00\x01"
        b"\x00\x01"
        b"\x00\x00\x00\x3C"
        b"\x00\x04"
        + bytes([0, 0, 0, 0])
    )
    packet = header + question + answer
    ips = parse_dns_a_record(packet)
    assert ips == ["0.0.0.0"]


# ── Report Generation Tests ────────────────────────────────────────────────


def test_print_terminal_report_exit_codes(capsys):
    pass_res = [AuditResult("Test 1", "PASS", "details")]
    warn_res = [AuditResult("Test 2", "WARN", "details")]
    fail_res = [AuditResult("Test 3", "FAIL", "details")]

    assert print_terminal_report(pass_res, []) == 0
    assert print_terminal_report(pass_res, warn_res) == 2
    assert print_terminal_report(pass_res, fail_res) == 1
    assert print_terminal_report(warn_res, fail_res) == 1


def test_print_json_report(capsys):
    pass_res = [AuditResult("Security Check", "PASS", "ok", 1.5, "ms")]
    exit_code = print_json_report(pass_res, [])
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["summary"]["pass"] == 1
    assert data["summary"]["fail"] == 0
    assert data["security"][0]["name"] == "Security Check"
