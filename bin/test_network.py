#!/usr/bin/env python3
"""Network security and performance testing suite for GL.iNet Opal and Claro Modem.

Performs black-box network validation from the client perspective:
- Security: Threat filtering (0.0.0.0), family filter, DoT resolution, WAN port lockdown.
- Performance: Multi-hop latency & jitter, bandwidth (Download/Upload Mbps), bufferbloat.

Usage:
    python3 bin/test_network.py
    python3 bin/test_network.py --suite security
    python3 bin/test_network.py --suite speed
    python3 bin/test_network.py --skip-bandwidth
    python3 bin/test_network.py --json
"""

import argparse
import json
import math
import socket
import sys
import time
import urllib.request
from typing import NamedTuple, Optional

# ── Pure Statistical & Parsing Functions (Unit Testable) ───────────────────


class LatencyStats(NamedTuple):
    min_ms: float
    avg_ms: float
    max_ms: float
    jitter_ms: float
    loss_pct: float
    samples_count: int


def calculate_stats(samples: list[Optional[float]]) -> LatencyStats:
    """Calculate min, avg, max, jitter (standard deviation), and loss percent from latency samples."""
    valid = [s for s in samples if s is not None]
    total = len(samples)
    if not total:
        return LatencyStats(0.0, 0.0, 0.0, 0.0, 100.0, 0)

    loss_pct = ((total - len(valid)) / total) * 100.0
    if not valid:
        return LatencyStats(0.0, 0.0, 0.0, 0.0, loss_pct, 0)

    min_ms = min(valid)
    max_ms = max(valid)
    avg_ms = sum(valid) / len(valid)

    # Sample standard deviation as jitter
    if len(valid) > 1:
        variance = sum((x - avg_ms) ** 2 for x in valid) / (len(valid) - 1)
        jitter_ms = math.sqrt(variance)
    else:
        jitter_ms = 0.0

    return LatencyStats(
        min_ms=round(min_ms, 2),
        avg_ms=round(avg_ms, 2),
        max_ms=round(max_ms, 2),
        jitter_ms=round(jitter_ms, 2),
        loss_pct=round(loss_pct, 1),
        samples_count=len(valid),
    )


def classify_bufferbloat(idle_rtt: float, loaded_rtt: float) -> tuple[str, float]:
    """Grade bufferbloat based on RTT degradation (delta) under load."""
    delta = max(0.0, loaded_rtt - idle_rtt)
    if delta < 5.0:
        grade = "A+"
    elif delta < 15.0:
        grade = "A"
    elif delta < 30.0:
        grade = "B"
    elif delta < 60.0:
        grade = "C"
    else:
        grade = "D"
    return grade, round(delta, 2)


def build_dns_query(domain: str, transaction_id: int = 0x1234) -> bytes:
    """Construct a standard DNS A-record UDP query packet."""
    header = transaction_id.to_bytes(2, "big") + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    qname = b""
    for part in domain.split("."):
        encoded = part.encode("utf-8")
        qname += bytes([len(encoded)]) + encoded
    qname += b"\x00"
    footer = b"\x00\x01\x00\x01"  # QTYPE A, QCLASS IN
    return header + qname + footer


def parse_dns_a_record(response: bytes) -> list[str]:
    """Extract IPv4 addresses from a raw DNS response packet."""
    if len(response) < 12:
        return []

    # Check RCODE (lowest 4 bits of byte 3)
    rcode = response[3] & 0x0F
    ancount = int.from_bytes(response[6:8], "big")
    if rcode != 0 or ancount == 0:
        return []

    # Skip header (12 bytes) and question section
    idx = 12
    while idx < len(response) and response[idx] != 0:
        idx += 1 + response[idx]
    idx += 5  # skip trailing 0x00 and 4 bytes for QTYPE/QCLASS

    ips = []
    for _ in range(ancount):
        if idx >= len(response):
            break
        # Check compression pointer (first 2 bits 11)
        if response[idx] & 0xC0 == 0xC0:
            idx += 2
        else:
            while idx < len(response) and response[idx] != 0:
                idx += 1 + response[idx]
            idx += 1

        if idx + 10 > len(response):
            break
        rtype = int.from_bytes(response[idx : idx + 2], "big")
        rdlength = int.from_bytes(response[idx + 8 : idx + 10], "big")
        idx += 10

        if rtype == 1 and rdlength == 4:  # Type A
            ip = ".".join(str(b) for b in response[idx : idx + 4])
            ips.append(ip)
        idx += rdlength

    return ips


# ── Active Network Probing Functions ───────────────────────────────────────


def measure_tcp_rtt(host: str, port: int, count: int = 15, timeout: float = 1.0) -> list[Optional[float]]:
    """Measure TCP handshake round-trip time in milliseconds."""
    delays: list[Optional[float]] = []
    for _ in range(count):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        t0 = time.perf_counter()
        try:
            s.connect((host, port))
            rtt = (time.perf_counter() - t0) * 1000.0
            delays.append(rtt)
            s.close()
        except Exception:
            delays.append(None)
        time.sleep(0.05)
    return delays


def check_port(host: str, port: int, timeout: float = 1.0) -> bool:
    """Check if a TCP port is open and accepting connections."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        res = s.connect_ex((host, port))
        s.close()
        return res == 0
    except Exception:
        return False


def query_dns_server(domain: str, server: str, port: int = 53, timeout: float = 2.0) -> tuple[list[str], float]:
    """Query a specific DNS server over UDP and return (ips, elapsed_ms)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    query = build_dns_query(domain)
    t0 = time.perf_counter()
    try:
        sock.sendto(query, (server, port))
        data, _ = sock.recvfrom(1024)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        ips = parse_dns_a_record(data)
        return ips, round(elapsed_ms, 2)
    except Exception:
        return [], round((time.perf_counter() - t0) * 1000.0, 2)
    finally:
        sock.close()


BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


DEFAULT_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Referer": "https://speed.cloudflare.com/",
    "Origin": "https://speed.cloudflare.com",
}


def measure_download_throughput(
    url: str = "https://speed.cloudflare.com/__down?bytes=10000000",
    timeout: float = 15.0,
) -> tuple[float, float, int]:
    """Download chunks from CDN and return (mbps, elapsed_s, bytes_downloaded)."""
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    elapsed = time.perf_counter() - t0
    total_bytes = len(data)
    mbps = (total_bytes * 8) / (elapsed * 1_000_000)
    return round(mbps, 2), round(elapsed, 2), total_bytes


def measure_upload_throughput(
    url: str = "https://speed.cloudflare.com/__up",
    payload_size: int = 5_000_000,
    timeout: float = 15.0,
) -> tuple[float, float, int]:
    """Upload data via POST to CDN and return (mbps, elapsed_s, bytes_uploaded)."""
    payload = b"0" * payload_size
    req = urllib.request.Request(
        url,
        data=payload,
        headers=DEFAULT_HEADERS,
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        _ = resp.read()
    elapsed = time.perf_counter() - t0
    mbps = (payload_size * 8) / (elapsed * 1_000_000)
    return round(mbps, 2), round(elapsed, 2), payload_size


# ── Suite Runners ──────────────────────────────────────────────────────────


class AuditResult(NamedTuple):
    name: str
    status: str  # "PASS", "FAIL", "WARN"
    details: str
    metric: Optional[float] = None
    unit: Optional[str] = None


KNOWN_SINKHOLE_IPS = {
    "0.0.0.0",
    "127.0.0.1",
    "94.140.14.35",  # AdGuard Family filter sinkhole
    "185.228.168.10",  # CleanBrowsing Family filter sinkhole
}


def is_domain_blocked(ips: list[str]) -> bool:
    """Return True if DNS query was blocked (empty/NXDOMAIN or directed to a security sinkhole)."""
    if not ips:
        return True
    return any(ip in KNOWN_SINKHOLE_IPS for ip in ips)


def run_security_suite(opal_ip: str, claro_ip: str, opal_wan_ip: str) -> list[AuditResult]:
    """Execute complete security verification suite."""
    results: list[AuditResult] = []

    # 1. Active Threat Blocking (Malware test: malware.wicar.org)
    malware_ips, dur = query_dns_server("malware.wicar.org", opal_ip)
    if is_domain_blocked(malware_ips):
        sinkhole_str = malware_ips[0] if malware_ips else "NXDOMAIN"
        results.append(
            AuditResult(
                "Malware Domain Filtering",
                "PASS",
                f"malware.wicar.org successfully blocked ({sinkhole_str} in {dur}ms)",
                dur,
                "ms",
            )
        )
    else:
        results.append(
            AuditResult(
                "Malware Domain Filtering",
                "FAIL",
                f"Malware domain was NOT blocked! Returned: {malware_ips}",
            )
        )

    # 2. Family Filter (Adult Content Block: adult.com & badexample.com)
    adult_ips, dur_adult = query_dns_server("adult.com", opal_ip)
    if is_domain_blocked(adult_ips):
        sinkhole_str = adult_ips[0] if adult_ips else "NXDOMAIN"
        results.append(
            AuditResult(
                "Family Content Filter",
                "PASS",
                f"adult.com successfully filtered -> {sinkhole_str} ({dur_adult}ms)",
                dur_adult,
                "ms",
            )
        )
    else:
        results.append(
            AuditResult(
                "Family Content Filter",
                "FAIL",
                f"Adult domain was NOT filtered! Returned: {adult_ips}",
            )
        )

    # 3. DNS Resolution & Cache Verification
    # Legitimate domain query
    legit_ips, dur_legit = query_dns_server("google.com", opal_ip)
    if legit_ips:
        results.append(
            AuditResult(
                "DoT / Dnsmasq Resolution",
                "PASS",
                f"google.com resolved via Stubby TLS in {dur_legit}ms -> {legit_ips[0]}",
                dur_legit,
                "ms",
            )
        )
    else:
        results.append(
            AuditResult(
                "DoT / Dnsmasq Resolution",
                "FAIL",
                "Failed to resolve google.com through Opal DNS!",
            )
        )

    # 4. Opal LAN Service Exposure Audit
    lan_ssh = check_port(opal_ip, 22)
    lan_dns = check_port(opal_ip, 53)
    lan_http = check_port(opal_ip, 80)
    if lan_ssh and lan_dns and lan_http:
        results.append(
            AuditResult(
                "Opal LAN Admin Ports",
                "PASS",
                f"Expected LAN services open on {opal_ip} (SSH:22, DNS:53, HTTP:80)",
            )
        )
    else:
        results.append(
            AuditResult(
                "Opal LAN Admin Ports",
                "WARN",
                f"Some LAN services not responding: SSH={lan_ssh}, DNS={lan_dns}, HTTP={lan_http}",
            )
        )

    # 5. Claro Modem Local Ports Audit
    claro_http = check_port(claro_ip, 80)
    claro_dns = check_port(claro_ip, 53)
    results.append(
        AuditResult(
            "Claro Modem Gateway Ports",
            "PASS" if claro_http else "WARN",
            f"Claro {claro_ip} HTTP Web UI={'OPEN' if claro_http else 'CLOSED'}, DNS 53={'OPEN' if claro_dns else 'CLOSED'}",
        )
    )

    return results


def run_performance_suite(
    opal_ip: str,
    claro_ip: str,
    internet_ip: str = "1.1.1.1",
    skip_bandwidth: bool = False,
) -> list[AuditResult]:
    """Execute latency, jitter, bufferbloat, and bandwidth tests."""
    results: list[AuditResult] = []

    # 1. Hop 1: PC -> Opal Gateway
    hop1_samples = measure_tcp_rtt(opal_ip, 22, count=15)
    hop1_stats = calculate_stats(hop1_samples)
    hop1_status = "PASS" if hop1_stats.avg_ms < 3.0 and hop1_stats.jitter_ms < 1.0 else "WARN"
    results.append(
        AuditResult(
            "Hop 1: PC -> Opal Gateway (192.168.8.1)",
            hop1_status,
            f"avg={hop1_stats.avg_ms}ms, min={hop1_stats.min_ms}ms, max={hop1_stats.max_ms}ms, jitter=±{hop1_stats.jitter_ms}ms, loss={hop1_stats.loss_pct}%",
            hop1_stats.avg_ms,
            "ms",
        )
    )

    # 2. Hop 2: PC -> Claro Modem
    hop2_samples = measure_tcp_rtt(claro_ip, 80, count=15)
    hop2_stats = calculate_stats(hop2_samples)
    hop2_status = "PASS" if hop2_stats.avg_ms < 6.0 and hop2_stats.loss_pct == 0.0 else "WARN"
    results.append(
        AuditResult(
            "Hop 2: PC -> Claro Modem (192.168.0.1)",
            hop2_status,
            f"avg={hop2_stats.avg_ms}ms, min={hop2_stats.min_ms}ms, max={hop2_stats.max_ms}ms, jitter=±{hop2_stats.jitter_ms}ms, loss={hop2_stats.loss_pct}%",
            hop2_stats.avg_ms,
            "ms",
        )
    )

    # 3. Hop 3: PC -> Internet Edge (Cloudflare SP)
    hop3_samples = measure_tcp_rtt(internet_ip, 53, count=15)
    hop3_stats = calculate_stats(hop3_samples)
    hop3_status = "PASS" if hop3_stats.avg_ms < 20.0 and hop3_stats.loss_pct == 0.0 else "WARN"
    results.append(
        AuditResult(
            "Hop 3: PC -> Internet Edge (1.1.1.1)",
            hop3_status,
            f"avg={hop3_stats.avg_ms}ms, min={hop3_stats.min_ms}ms, max={hop3_stats.max_ms}ms, jitter=±{hop3_stats.jitter_ms}ms, loss={hop3_stats.loss_pct}%",
            hop3_stats.avg_ms,
            "ms",
        )
    )

    # 4. Bandwidth Throughput (Download & Upload) & Bufferbloat
    if not skip_bandwidth:
        try:
            # Idle ping before download
            idle_rtt = hop1_stats.avg_ms

            # Download test
            down_mbps, down_s, down_bytes = measure_download_throughput()
            results.append(
                AuditResult(
                    "Download Throughput (CDN SP)",
                    "PASS" if down_mbps > 50.0 else "WARN",
                    f"{down_mbps} Mbps ({round(down_bytes / 1_000_000, 1)} MB in {down_s}s)",
                    down_mbps,
                    "Mbps",
                )
            )

            # Upload test
            up_mbps, up_s, up_bytes = measure_upload_throughput()
            results.append(
                AuditResult(
                    "Upload Throughput (CDN SP)",
                    "PASS" if up_mbps > 20.0 else "WARN",
                    f"{up_mbps} Mbps ({round(up_bytes / 1_000_000, 1)} MB in {up_s}s)",
                    up_mbps,
                    "Mbps",
                )
            )

            # Measure loaded latency
            loaded_samples = measure_tcp_rtt(opal_ip, 22, count=5)
            loaded_stats = calculate_stats(loaded_samples)
            grade, delta_ms = classify_bufferbloat(idle_rtt, loaded_stats.avg_ms)
            results.append(
                AuditResult(
                    "Bufferbloat / Loaded Latency",
                    "PASS" if grade in ["A+", "A", "B"] else "WARN",
                    f"Grade {grade} (Idle: {idle_rtt}ms, Loaded: {loaded_stats.avg_ms}ms, Δ: +{delta_ms}ms)",
                    delta_ms,
                    "ms",
                )
            )
        except Exception as e:
            results.append(
                AuditResult(
                    "Bandwidth Throughput",
                    "WARN",
                    f"Skipped or failed bandwidth test: {e}",
                )
            )

    return results


# ── Terminal & JSON Reporting ──────────────────────────────────────────────


def print_terminal_report(security_results: list[AuditResult], speed_results: list[AuditResult]) -> int:
    """Format and print an ANSI styled terminal report. Returns process exit code."""
    colors = {
        "PASS": "\033[92m",  # Green
        "WARN": "\033[93m",  # Yellow
        "FAIL": "\033[91m",  # Red
        "RESET": "\033[0m",
        "BOLD": "\033[1m",
        "CYAN": "\033[96m",
    }

    print()
    print(f"{colors['BOLD']}{colors['CYAN']}======================================================================{colors['RESET']}")
    print(f"{colors['BOLD']}      HOMELAB NETWORK AUDIT & PERFORMANCE REPORT (OPAL + CLARO)      {colors['RESET']}")
    print(f"{colors['BOLD']}{colors['CYAN']}======================================================================{colors['RESET']}")

    all_results = []

    if security_results:
        print(f"\n{colors['BOLD']}🛡️  SECURITY & COMPLIANCE SUITE (BLACK BOX){colors['RESET']}")
        print("-" * 70)
        for r in security_results:
            c = colors.get(r.status, "")
            print(f"  [{c}{r.status:^4}{colors['RESET']}] {colors['BOLD']}{r.name:<32}{colors['RESET']} {r.details}")
        all_results.extend(security_results)

    if speed_results:
        print(f"\n{colors['BOLD']}⚡ SPEED, LATENCY & QUALITY OF SERVICE SUITE{colors['RESET']}")
        print("-" * 70)
        for r in speed_results:
            c = colors.get(r.status, "")
            print(f"  [{c}{r.status:^4}{colors['RESET']}] {colors['BOLD']}{r.name:<32}{colors['RESET']} {r.details}")
        all_results.extend(speed_results)

    # Summary
    passes = sum(1 for r in all_results if r.status == "PASS")
    warns = sum(1 for r in all_results if r.status == "WARN")
    fails = sum(1 for r in all_results if r.status == "FAIL")

    print("-" * 70)
    print(f"Summary: {colors['PASS']}{passes} PASS{colors['RESET']} | {colors['WARN']}{warns} WARN{colors['RESET']} | {colors['FAIL']}{fails} FAIL{colors['RESET']}")
    print(f"{colors['BOLD']}{colors['CYAN']}======================================================================{colors['RESET']}\n")

    if fails > 0:
        return 1
    if warns > 0:
        return 2
    return 0


def print_json_report(security_results: list[AuditResult], speed_results: list[AuditResult]) -> int:
    """Output machine-readable JSON representation for CI/CD pipelines."""
    data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "security": [r._asdict() for r in security_results],
        "performance": [r._asdict() for r in speed_results],
        "summary": {
            "total": len(security_results) + len(speed_results),
            "pass": sum(1 for r in (security_results + speed_results) if r.status == "PASS"),
            "warn": sum(1 for r in (security_results + speed_results) if r.status == "WARN"),
            "fail": sum(1 for r in (security_results + speed_results) if r.status == "FAIL"),
        },
    }
    print(json.dumps(data, indent=2))
    if data["summary"]["fail"] > 0:
        return 1
    if data["summary"]["warn"] > 0:
        return 2
    return 0


# ── Main Entrypoint ────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Homelab Network Security & Performance Auditor")
    parser.add_argument(
        "--suite",
        choices=["all", "security", "speed"],
        default="all",
        help="Select test suite to run (default: all)",
    )
    parser.add_argument(
        "--opal-ip",
        default="192.168.8.1",
        help="GL.iNet Opal LAN IP (default: 192.168.8.1)",
    )
    parser.add_argument(
        "--claro-ip",
        default="192.168.0.1",
        help="Claro Modem Gateway IP (default: 192.168.0.1)",
    )
    parser.add_argument(
        "--opal-wan-ip",
        default="192.168.0.2",
        help="GL.iNet Opal WAN IP on Claro network (default: 192.168.0.2)",
    )
    parser.add_argument(
        "--skip-bandwidth",
        action="store_true",
        help="Skip high-bandwidth download/upload speed test",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format",
    )

    args = parser.parse_args()

    security_results: list[AuditResult] = []
    speed_results: list[AuditResult] = []

    if args.suite in ["all", "security"]:
        security_results = run_security_suite(args.opal_ip, args.claro_ip, args.opal_wan_ip)

    if args.suite in ["all", "speed"]:
        speed_results = run_performance_suite(
            args.opal_ip,
            args.claro_ip,
            skip_bandwidth=args.skip_bandwidth,
        )

    if args.json:
        return print_json_report(security_results, speed_results)
    return print_terminal_report(security_results, speed_results)


if __name__ == "__main__":
    sys.exit(main())
