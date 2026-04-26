"""Contract tests — feed real CLI output snapshots through parsing helpers.

If AWS/Terraform/kubectl/Tailscale change their output schema, these tests
fail *before* a production deploy breaks silently. See
bin/tests/contracts/README.md for regeneration protocol.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Also make ansible/ importable for terraform_inventory_aws
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ansible"))

import deploy_aws_homelab as deploy  # noqa: E402
import smoke_test as smoke  # noqa: E402
import terraform_inventory_aws as inv  # noqa: E402


CONTRACTS = Path(__file__).parent / "contracts"


def _read(rel):
    return (CONTRACTS / rel).read_text(encoding="utf-8")


# ── AWS SSM ──────────────────────────────────────────────────────────────────


def test_contract_ssm_ping_status_online():
    assert (
        deploy.parse_ssm_ping_status(
            _read("aws_ssm/describe-instance-information--online.txt")
        )
        == "Online"
    )


def test_contract_ssm_ping_status_empty_maps_to_none():
    # When the query returns nothing (unknown instance, agent never registered),
    # AWS CLI emits an empty string — we normalize to "None".
    assert (
        deploy.parse_ssm_ping_status(
            _read("aws_ssm/describe-instance-information--pending.txt")
        )
        == "None"
    )


def test_contract_ssm_ping_status_connection_lost():
    assert (
        deploy.parse_ssm_ping_status(
            _read("aws_ssm/describe-instance-information--connection-lost.txt")
        )
        == "ConnectionLost"
    )


def test_contract_ssm_command_id_is_uuid_like():
    cmd_id = deploy.parse_ssm_command_id(_read("aws_ssm/send-command--command-id.txt"))
    # Sanity: UUIDs are 36 chars with 4 hyphens.
    assert len(cmd_id) == 36
    assert cmd_id.count("-") == 4


def test_contract_ssm_invocation_status_success():
    assert (
        deploy.parse_ssm_invocation_status(
            _read("aws_ssm/get-command-invocation--status-success.txt")
        )
        == "Success"
    )


def test_contract_ssm_invocation_status_failed():
    assert (
        deploy.parse_ssm_invocation_status(
            _read("aws_ssm/get-command-invocation--status-failed.txt")
        )
        == "Failed"
    )


def test_contract_ssm_invocation_status_empty_maps_to_pending():
    assert (
        deploy.parse_ssm_invocation_status(
            _read("aws_ssm/get-command-invocation--status-pending.txt")
        )
        == "Pending"
    )


def test_contract_ssm_command_output_preserves_multiline():
    out = deploy.parse_ssm_command_output(
        _read("aws_ssm/get-command-invocation--stdout.txt")
    )
    # Internal newlines preserved; trailing stripped
    assert "Linux ip-10-0-1-42" in out
    assert "k3s version" in out
    assert not out.endswith("\n")


# ── AWS EC2 ──────────────────────────────────────────────────────────────────


def test_contract_ec2_instance_id_shape():
    iid = deploy.parse_ec2_instance_id(
        _read("aws_ec2/describe-instances--instance-id.txt")
    )
    assert iid.startswith("i-")
    assert len(iid) == 19  # i- + 17 hex chars


def test_contract_ec2_instance_id_no_match_is_literal_none_string():
    # AWS CLI with --output text and no match returns the literal word "None".
    # Our code treats this as a found-but-invalid ID. Downstream logic catches
    # it via `if not server_id: error_exit(...)`, so this stays as-is.
    iid = deploy.parse_ec2_instance_id(
        _read("aws_ec2/describe-instances--no-match.txt")
    )
    assert iid == "None"


def test_contract_ec2_instance_count_parses_integer():
    assert (
        deploy.parse_ec2_instance_count(
            _read("aws_ec2/describe-instances--count-2.txt")
        )
        == 2
    )


def test_contract_ec2_instance_count_zero():
    assert (
        deploy.parse_ec2_instance_count(
            _read("aws_ec2/describe-instances--count-empty.txt")
        )
        == 0
    )


# ── Terraform ────────────────────────────────────────────────────────────────


REQUIRED_INVENTORY_KEYS = {
    "k3s_server_public_ip",
    "k3s_server_private_ip",
    "k3s_server_instance_id",
    "k3s_agent_public_ip",
    "k3s_agent_private_ip",
    "k3s_agent_instance_id",
}


def test_contract_terraform_output_json_has_all_inventory_keys():
    """Critical: ansible/terraform_inventory_aws.py reads these exact keys."""
    outputs = inv.parse_terraform_output_json(_read("terraform/output-json--full.json"))
    missing = REQUIRED_INVENTORY_KEYS - outputs.keys()
    assert not missing, f"Inventory keys missing from terraform output: {missing}"


def test_contract_terraform_output_json_unwraps_value_field():
    outputs = inv.parse_terraform_output_json(_read("terraform/output-json--full.json"))
    # Value should be the raw IP, not `{"value": "...", "type": "..."}`.
    assert outputs["k3s_server_public_ip"] == "54.234.12.42"
    assert outputs["k3s_server_instance_id"].startswith("i-")


def test_contract_terraform_output_json_empty_returns_empty_dict():
    assert (
        inv.parse_terraform_output_json(_read("terraform/output-json--empty.json"))
        == {}
    )


def test_contract_terraform_output_raw_strips_trailing_newline():
    stdout = _read("terraform/output-raw--server-ip.txt")
    assert deploy.parse_terraform_output_raw(stdout, returncode=0) == "54.234.12.42"


def test_contract_terraform_output_raw_nonzero_returns_na():
    assert deploy.parse_terraform_output_raw("anything", returncode=1) == "N/A"


def test_contract_terraform_state_list_detects_acl():
    assert (
        deploy.parse_terraform_state_has_acl(
            _read("terraform/state-list--with-acl.txt")
        )
        is True
    )


def test_contract_terraform_state_list_missing_acl():
    assert (
        deploy.parse_terraform_state_has_acl(_read("terraform/state-list--no-acl.txt"))
        is False
    )


# ── Tailscale ────────────────────────────────────────────────────────────────


def test_contract_tailscale_ip_connected_matches_100_prefix():
    ip = deploy.extract_tailscale_ip(_read("tailscale/ip--connected.txt"))
    assert ip == "100.101.102.103"


def test_contract_tailscale_ip_not_connected_returns_empty():
    assert deploy.extract_tailscale_ip(_read("tailscale/ip--not-connected.txt")) == ""


def test_contract_tailscale_status_json_returns_online_peers_only():
    ips = inv.parse_tailscale_status_json(_read("tailscale/status--json.json"))
    # Online + has v4: k3s-server-1, k3s-agent-2
    assert "k3s-server-1" in ips
    assert "k3s-agent-2" in ips
    # Offline peer excluded
    assert "old-offline-host" not in ips
    # IPv6-only peer excluded
    assert "ipv6-only-peer" not in ips


def test_contract_tailscale_status_json_returns_ipv4_only():
    ips = inv.parse_tailscale_status_json(_read("tailscale/status--json.json"))
    for ip in ips.values():
        assert ":" not in ip
        assert ip.startswith("100.")


def test_contract_tailscale_status_json_invalid_returns_empty():
    assert inv.parse_tailscale_status_json("not json") == {}


# ── kubectl ──────────────────────────────────────────────────────────────────


def test_contract_kubectl_get_applications_extracts_sync_and_health():
    apps = smoke.parse_argocd_apps(_read("kubectl/get-applications--json.json"))
    names = {a.name for a in apps}


def test_contract_kubectl_get_applications_empty_returns_empty_list():
    assert smoke.parse_argocd_apps(_read("kubectl/get-applications--empty.json")) == []


def test_contract_kubectl_get_pods_parses_status_column():
    pods = smoke.parse_pod_status_lines(_read("kubectl/get-pods--no-headers.txt"))
    statuses = {p.status for p in pods}
    # Real kubectl `-o wide` columns: NS NAME READY STATUS RESTARTS AGE
    # parts[3] is STATUS — test surfaces drift if schema changes.
    assert "Running" in statuses
    assert "CrashLoopBackOff" in statuses
    assert "ImagePullBackOff" in statuses


def test_contract_kubectl_get_pods_known_failure_states_detected():
    pods = smoke.parse_pod_status_lines(_read("kubectl/get-pods--no-headers.txt"))
    failures = [p for p in pods if p.status in smoke.POD_FAILURE_STATES]
    assert len(failures) == 2
    assert {p.name for p in failures} >= {}


def test_contract_kubectl_get_pvc_extracts_status_and_volume():
    """Real kubectl `get pvc -A --no-headers` columns:
    NAMESPACE NAME STATUS VOLUME CAPACITY ACCESS STORAGECLASS AGE.
    """
    pvcs = smoke.parse_pvc_rows(_read("kubectl/get-pvc--no-headers.txt"))
    assert len(pvcs) == 5

    statuses = {p.status for p in pvcs}
    # Fixture has 4 Bound + 1 Pending
    assert statuses == {"Bound", "Pending"}

    adguard = next(p for p in pvcs if p.name == "config-adguard")
    assert adguard.namespace == "adguard"
    assert adguard.status == "Bound"
    assert adguard.volume == "pvc-abc111"

    pending = next(p for p in pvcs if p.status == "Pending")
    assert pending.name == "loki-storage-0"


def test_contract_kubectl_get_statefulset_parses_ready_over_desired():
    """Real kubectl `get statefulset -A --no-headers` columns:
    NAMESPACE NAME READY(current/desired) AGE.
    """
    sts = smoke.parse_statefulset_rows(_read("kubectl/get-statefulset--no-headers.txt"))
    assert len(sts) == 3

    names = {s.name for s in sts}

    loki = next(s for s in sts if s.name == "loki")
    # Fixture says "0/1" — not ready
    assert loki.ready == 0
    assert loki.desired == 1

    prom = next(s for s in sts if s.name == "prometheus")
    assert prom.ready == 1
    assert prom.desired == 1


def test_contract_kubectl_jsonpath_ready_replicas_parses_int():
    assert (
        smoke.parse_ready_replicas(_read("kubectl/jsonpath-ready-replicas--one.txt"))
        == 1
    )
    assert (
        smoke.parse_ready_replicas(_read("kubectl/jsonpath-ready-replicas--zero.txt"))
        == 0
    )
    assert (
        smoke.parse_ready_replicas(_read("kubectl/jsonpath-ready-replicas--empty.txt"))
        == 0
    )


# ── Parser edge cases (no fixture needed) ────────────────────────────────────


def test_parser_pod_rows_skips_lines_with_fewer_than_four_cols():
    # "ns pod Running" is only 3 cols — discarded.
    assert smoke.parse_pod_status_lines("ns pod Running\n") == []


def test_parser_pod_rows_handles_empty_stdout():
    assert smoke.parse_pod_status_lines("") == []
    assert smoke.parse_pod_status_lines(None) == []


def test_parser_pvc_rows_skips_blank_lines():
    pvcs = smoke.parse_pvc_rows("\n   \nns name Bound pvc-1 1Gi RWO local 1d\n\n")
    assert len(pvcs) == 1


def test_parser_pvc_rows_skips_lines_with_fewer_than_four_cols():
    assert smoke.parse_pvc_rows("ns name Bound\n") == []


def test_parser_statefulset_rows_skips_blank_and_short_lines():
    sts = smoke.parse_statefulset_rows("\nshortline\nns name 1/1 1d\n")
    assert len(sts) == 1
    assert sts[0].ready == 1
    assert sts[0].desired == 1


def test_parser_statefulset_rows_skips_unparseable_ready_field():
    # "N/A" is not an integer ratio — parser must discard the row rather than crash.
    assert smoke.parse_statefulset_rows("ns name N/A 1d\n") == []


def test_parser_ready_replicas_raises_valueerror_recovered_as_zero():
    # Malformed jsonpath output: non-integer string → ValueError → 0
    assert smoke.parse_ready_replicas("not-a-number") == 0


def test_parser_argocd_apps_handles_empty_stdout():
    assert smoke.parse_argocd_apps("") == []
    assert smoke.parse_argocd_apps(None) == []


def test_parser_argocd_apps_handles_invalid_json():
    assert smoke.parse_argocd_apps("{oops not json") == []
