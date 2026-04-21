"""Offline checks that required OPA policy files exist."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICIES = REPO_ROOT / "k8s" / "policies"

REQUIRED_POLICIES = {
    "security_context.rego",
    "resource_limits.rego",
    "health_probes.rego",
    "rbac_safety.rego",
}


def test_all_required_policy_files_exist():
    present = {p.name for p in POLICIES.glob("*.rego")}
    missing = REQUIRED_POLICIES - present
    assert not missing, f"Missing OPA policy files: {sorted(missing)}"
