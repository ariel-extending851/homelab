"""Security guardrail tests for configuration files.

These tests are static and CI-safe; no cloud access is required.
"""

from pathlib import Path
import re


REPO_ROOT = Path(__file__).resolve().parents[2]
GROUP_VARS = REPO_ROOT / "ansible" / "group_vars"
OPENSSH_PRIVATE_KEY_MARKER = "-----BEGIN OPENSSH PRIVATE" + " KEY-----"
RSA_PRIVATE_KEY_MARKER = "-----BEGIN RSA PRIVATE" + " KEY-----"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestSopsEncryptedFiles:
    def test_sops_files_exist(self):
        sops_files = sorted(GROUP_VARS.glob("*.sops.yml"))
        assert sops_files, "Expected encrypted SOPS files in ansible/group_vars"

    def test_sops_files_contain_encrypted_values_and_metadata(self):
        for path in sorted(GROUP_VARS.glob("*.sops.yml")):
            content = _read(path)
            assert "sops:" in content, f"Missing SOPS metadata block in {path.name}"
            assert "ENC[" in content, f"Expected encrypted values in {path.name}"
            assert (
                "version:" in content
            ), f"Missing SOPS version metadata in {path.name}"

    def test_router_example_is_plaintext_template_only(self):
        example = GROUP_VARS / "router.sops.yaml.example"
        assert example.exists(), "Missing router.sops.yaml.example"
        content = _read(example)
        assert "REPLACE_WITH_REAL_WIFI_PASSWORD" in content
        assert "ENC[" not in content


class TestPlaintextSecretLeakage:
    def test_no_private_keys_committed_in_group_vars(self):
        for path in sorted(GROUP_VARS.glob("*.yml")) + sorted(
            GROUP_VARS.glob("*.yaml")
        ):
            content = _read(path)
            assert (
                OPENSSH_PRIVATE_KEY_MARKER not in content
            ), f"Private key marker found in {path.name}"
            assert (
                RSA_PRIVATE_KEY_MARKER not in content
            ), f"Private key marker found in {path.name}"

    def test_non_sops_group_vars_do_not_define_wifi_passwords(self):
        forbidden = re.compile(r"^\s*wifi(_guest)?_password\s*:\s*", re.IGNORECASE)
        for path in sorted(GROUP_VARS.glob("*.yml")) + sorted(
            GROUP_VARS.glob("*.yaml")
        ):
            if ".sops." in path.name or path.name.endswith(".example"):
                continue
            for line in _read(path).splitlines():
                assert not forbidden.search(
                    line
                ), f"Potential plaintext wifi credential key found in {path.name}"


class TestPolicyGuardrails:
    def test_tailscale_acl_exists_and_has_expected_sections(self):
        acl_path = REPO_ROOT / "infra" / "aws" / "acl.json"
        content = _read(acl_path)
        assert '"acls"' in content
        assert '"ssh"' in content
        assert '"tagOwners"' in content

    def test_compute_module_iam_policy_scoped_to_transfer_bucket(self):
        compute_main = REPO_ROOT / "infra" / "aws" / "modules" / "compute" / "main.tf"
        content = _read(compute_main)
        assert "AmazonSSMManagedInstanceCore" in content
        assert "arn:aws:s3:::${var.ssm_s3_bucket}/*" in content
