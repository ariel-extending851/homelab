#!/usr/bin/env python3
"""Inspect the Opal router's current DNS posture over SSH.

Prints: failover state, active dnsmasq upstream, sample queries (positive +
negative against a gambling sentinel), and the cron entry. Diagnostic only —
not for automation.

Override target host with OPAL=192.168.x.y if needed.
"""
import os
import subprocess
import sys

OPAL = os.environ.get("OPAL", "192.168.8.1")
SSH_OPTS = [
    "-o",
    "HostKeyAlgorithms=+ssh-rsa",
    "-o",
    "PubkeyAcceptedAlgorithms=+ssh-rsa",
    "-o",
    "RequiredRSASize=1024",
    "-o",
    "ConnectTimeout=5",
]

REMOTE = r"""
echo '=== Failover state ==='
cat /var/run/adguard-failover.state 2>/dev/null || echo '(no state file — cron not run yet)'
echo
echo '=== dnsmasq upstream (active) ==='
uci -q get dhcp.@dnsmasq[0].server | tr ' ' '\n'
echo
echo '=== Sample resolution: should resolve to a real IP ==='
nslookup google.com 127.0.0.1 2>&1 | grep -E 'Address|Name'
echo
echo '=== Sample resolution: should be BLOCKED with Mullvad family/all ==='
nslookup bet365.com 127.0.0.1 2>&1 | grep -E 'Address|Name|NXDOMAIN|0\.0\.0\.0' || echo '(no match)'
echo
echo '=== Cron entry ==='
crontab -l | grep adguard-failover || echo '(missing)'
"""


def main() -> int:
    cmd = ["ssh", *SSH_OPTS, f"root@{OPAL}", REMOTE]
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
