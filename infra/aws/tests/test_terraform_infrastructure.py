"""Static Terraform infrastructure guardrails — no AWS calls required."""

from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
MAIN_TF = ROOT / "main.tf"
OUTPUTS_TF = ROOT / "outputs.tf"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestS3SecurityControls:
    """Critical S3 security settings that must not be accidentally removed."""

    def test_ssm_bucket_blocks_all_public_access(self):
        content = _read(MAIN_TF)
        assert "aws_s3_bucket_public_access_block" in content
        assert "block_public_acls       = true" in content
        assert "restrict_public_buckets = true" in content

    def test_ssm_bucket_has_server_side_encryption(self):
        content = _read(MAIN_TF)
        assert "aws_s3_bucket_server_side_encryption_configuration" in content

    def test_ssm_bucket_has_versioning_enabled(self):
        content = _read(MAIN_TF)
        assert "aws_s3_bucket_versioning" in content
        assert 'status = "Enabled"' in content

    def test_backend_uses_encrypted_s3_with_locking(self):
        content = _read(MAIN_TF)
        assert 'backend "s3"' in content
        assert "encrypt      = true" in content
        assert "use_lockfile = true" in content


class TestOutputContracts:
    """Verify required Terraform outputs exist so downstream consumers don't break."""

    @pytest.mark.parametrize(
        "output_name",
        [
            "vpc_id",
            "security_group_id",
            "k3s_server_public_ip",
            "k3s_server_private_ip",
            "k3s_agent_public_ip",
            "k3s_agent_private_ip",
            "k3s_server_instance_id",
            "k3s_agent_instance_id",
            "k3s_api_endpoint",
            "estimated_monthly_cost_usd",
        ],
    )
    def test_root_output_exists(self, output_name: str):
        assert f'output "{output_name}"' in _read(OUTPUTS_TF)

    @pytest.mark.parametrize(
        "module_rel, expected_outputs",
        [
            ("modules/network/outputs.tf", ["vpc_id", "security_group_id"]),
            (
                "modules/compute/outputs.tf",
                ["k3s_server_public_ip", "k3s_agent_public_ip"],
            ),
            ("modules/scheduler/outputs.tf", ["lambda_function_url"]),
        ],
    )
    def test_module_output_contracts(self, module_rel: str, expected_outputs: list):
        output_file = ROOT / module_rel
        assert output_file.exists(), f"Missing: {module_rel}"
        content = _read(output_file)
        for name in expected_outputs:
            assert f'output "{name}"' in content
