#!/usr/bin/env python3
"""Pipeline Gate (PR + Nightly).

Reads a JSON map of needs (job name → {result}) from stdin and exits non-zero
if any REQUIRED job did not succeed. ADVISORY jobs are reported but never
gate the run. Other jobs must end as `success` or `skipped`.

Pulled out of the embedded `run: |` block in ci-validation.yml because
actionlint's shellcheck pass kept flagging the Python `{set, literals,}` as
shell-syntax errors. Living in a .py file lets the workflow stay clean and
this logic stay readable.

Usage:
    echo "$NEEDS_JSON" | python3 .github/scripts/pipeline_gate.py [pr|nightly]
"""

import json
import sys

PR_REQUIRED = frozenset(
    [
        "disaster-recovery-execution",
        "policy-as-code-critical",
        "trivy-image-scan",
        "sops-validation",
        "qa-audit-evidence",
        "offline-required-profile",
        "python-tests-collect",
    ]
)

# Pinned ADVISORY during the self-hosted runner migration (PR #135 follow-up):
# the Pipeline Gate prints "[ADVISORY] <job>=<result>" instead of failing on
# these. All five have environment-specific failures unrelated to repo content:
#   - molecule: rpi_optimization role's sysctl_set returns "Invalid argument"
#     inside an unprivileged sibling container.
#   - arm64-validation: QEMU-emulated container lacks python3-apt.
#   - k8s-dry-run + k3d-convergence: Fedora Bluefin's firewalld filters
#     container-to-container traffic on the `kind` Docker network ("Packet
#     Filtered" from the bridge gateway), so the runner can't reach the kind
#     control-plane's apiserver port. Real fix: configure firewalld on the
#     pc-tower host to add Docker bridge interfaces to the trusted zone
#     (sudo firewall-cmd --permanent --zone=trusted
#      --add-interface=br-<kind-bridge>; firewall-cmd --reload).
# Promote back to REQUIRED once role/test/host fixes land.
PR_ADVISORY = frozenset(
    [
        "molecule",
        "arm64-validation",
        "k8s-dry-run",
        "k3d-convergence",
    ]
)

NIGHTLY_REQUIRED = frozenset(
    [
        "terraform",
        "yaml-lint",
        "k8s-dry-run",
        "shellcheck",
        "security",
        "trivy-image-scan",
        "policy-as-code-critical",
        "disaster-recovery-tests",
        "disaster-recovery-execution",
        "enforce-molecule-tests",
        "shell-tests",
        "python-tests",
        "sops-validation",
        "qa-audit-evidence",
        "offline-required-profile",
        "nightly-e2e-live",
        "lint-workflows",
    ]
)

NIGHTLY_ADVISORY = frozenset(
    [
        "molecule",
        "arm64-validation",
    ]
)


def evaluate(needs: dict, required: frozenset, advisory: frozenset) -> int:
    failed = []
    for name, data in needs.items():
        result = data.get("result", "missing")
        if name in required:
            if result != "success":
                failed.append(f"{name}={result}")
        elif name in advisory:
            if result != "success":
                print(f"[ADVISORY] {name}={result} (not gating)")
        elif result not in ("success", "skipped"):
            failed.append(f"{name}={result}")

    if failed:
        print("[FAIL] Pipeline gate failed: " + ", ".join(failed))
        return 1
    print("[OK] Required jobs passed; advisory failures are non-gating")
    return 0


def main(argv: list) -> int:
    mode = argv[1] if len(argv) > 1 else "pr"
    needs = json.load(sys.stdin)
    if mode == "nightly":
        return evaluate(needs, NIGHTLY_REQUIRED, NIGHTLY_ADVISORY)
    return evaluate(needs, PR_REQUIRED, PR_ADVISORY)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
