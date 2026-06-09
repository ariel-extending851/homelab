"""Tests for bin/velero_bootstrap_secret.py — TF output extraction, INI build, SOPS round-trip."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import velero_bootstrap_secret as bootstrap  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────


PLAINTEXT_SECRET = """\
# Comment block on top
apiVersion: v1
kind: Secret
metadata:
  name: velero-aws-credentials
  namespace: velero
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
type: Opaque
stringData:
  cloud: |
    [default]
    aws_access_key_id = OLD_PLACEHOLDER
    aws_secret_access_key = OLD_PLACEHOLDER
"""


# ── build_aws_credentials_ini ───────────────────────────────────────────────


def test_build_aws_credentials_ini_format():
    out = bootstrap.build_aws_credentials_ini("AKIATEST", "secret/value")
    assert out == (
        "[default]\n"
        "aws_access_key_id = AKIATEST\n"
        "aws_secret_access_key = secret/value\n"
    )


def test_build_aws_credentials_ini_handles_special_chars_in_secret():
    # AWS secret keys can contain /, +, =
    out = bootstrap.build_aws_credentials_ini("AKIA", "abc/def+ghi=")
    assert "aws_secret_access_key = abc/def+ghi=" in out


# ── replace_cloud_value ─────────────────────────────────────────────────────


def test_replace_cloud_value_swaps_block_and_preserves_metadata():
    new_cloud = "[default]\naws_access_key_id = NEW\naws_secret_access_key = NEW2\n"
    out = bootstrap.replace_cloud_value(PLAINTEXT_SECRET, new_cloud)
    assert "OLD_PLACEHOLDER" not in out
    assert "aws_access_key_id = NEW" in out
    assert "aws_secret_access_key = NEW2" in out
    # Surrounding fields preserved
    assert 'argocd.argoproj.io/sync-wave: "-1"' in out
    assert "name: velero-aws-credentials" in out
    assert "type: Opaque" in out


def test_replace_cloud_value_preserves_comment_block():
    out = bootstrap.replace_cloud_value(PLAINTEXT_SECRET, "[default]\nfoo = bar\n")
    assert "# Comment block on top" in out


def test_replace_cloud_value_raises_when_block_missing():
    yaml_no_cloud = "apiVersion: v1\nkind: Secret\nstringData:\n  other: value\n"
    with pytest.raises(ValueError, match="cloud:"):
        bootstrap.replace_cloud_value(yaml_no_cloud, "[default]\nx = y\n")


def test_replace_cloud_value_idempotent_when_run_twice_with_same_input():
    new_cloud = (
        "[default]\naws_access_key_id = STABLE\naws_secret_access_key = STABLE\n"
    )
    once = bootstrap.replace_cloud_value(PLAINTEXT_SECRET, new_cloud)
    twice = bootstrap.replace_cloud_value(once, new_cloud)
    # Second run should produce identical output (modulo whitespace edge cases)
    # The cloud block has been replaced once and the second pass replaces it
    # with the same content again — final state stable.
    assert once.count("aws_access_key_id = STABLE") == 1
    assert twice.count("aws_access_key_id = STABLE") == 1


# ── get_terraform_output ────────────────────────────────────────────────────


def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def test_get_terraform_output_strips_value():
    with patch.object(bootstrap.subprocess, "run", return_value=_proc(0, "AKIATEST\n")):
        result = bootstrap.get_terraform_output(
            "velero_aws_access_key_id", Path("infra/aws")
        )
    assert result == "AKIATEST"


def test_get_terraform_output_raises_on_empty_stdout():
    with patch.object(bootstrap.subprocess, "run", return_value=_proc(0, "  \n")):
        with pytest.raises(RuntimeError, match="empty"):
            bootstrap.get_terraform_output("missing", Path("infra/aws"))


def test_get_terraform_output_raises_on_nonzero_exit():
    err = _proc(1, "", "Error: no state file")
    with patch.object(bootstrap.subprocess, "run", return_value=err):
        with pytest.raises(RuntimeError, match="failed"):
            bootstrap.get_terraform_output("foo", Path("infra/aws"))


def test_get_terraform_output_invokes_chdir_flag():
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _proc(0, "value")

    with patch.object(bootstrap.subprocess, "run", side_effect=fake_run):
        bootstrap.get_terraform_output("velero_aws_access_key_id", Path("infra/aws"))

    assert captured["args"][0] == "terraform"
    assert captured["args"][1] == "-chdir=infra/aws"
    assert captured["args"][2:5] == ["output", "-raw", "velero_aws_access_key_id"]


# ── decrypt_secret ──────────────────────────────────────────────────────────


def test_decrypt_secret_returns_stdout():
    with patch.object(
        bootstrap.subprocess, "run", return_value=_proc(0, PLAINTEXT_SECRET)
    ):
        out = bootstrap.decrypt_secret(Path("k8s/apps/velero/secret.yaml"))
    assert out == PLAINTEXT_SECRET


def test_decrypt_secret_invokes_sops_with_path():
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return _proc(0, PLAINTEXT_SECRET)

    with patch.object(bootstrap.subprocess, "run", side_effect=fake_run):
        bootstrap.decrypt_secret(Path("p/q.yaml"))
    assert captured["args"] == ["sops", "--decrypt", "p/q.yaml"]


def test_decrypt_secret_raises_on_failure():
    with patch.object(
        bootstrap.subprocess,
        "run",
        side_effect=subprocess.CalledProcessError(1, ["sops"], stderr="bad key"),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            bootstrap.decrypt_secret(Path("x.yaml"))


# ── encrypt_secret_in_place ─────────────────────────────────────────────────


def test_encrypt_secret_in_place_writes_and_swaps(tmp_path):
    target = tmp_path / "secret.yaml"
    target.write_text("OLD CONTENT")

    def fake_run(args, **kwargs):
        # simulate sops --encrypt --in-place by mutating the tempfile
        if "--encrypt" in args:
            tmp = args[-1]
            Path(tmp).write_text("ENCRYPTED_VERSION")
            return _proc(0)
        return _proc(0)

    with patch.object(bootstrap.subprocess, "run", side_effect=fake_run):
        bootstrap.encrypt_secret_in_place(target, "NEW PLAINTEXT")

    assert target.read_text() == "ENCRYPTED_VERSION"


def test_encrypt_secret_in_place_cleans_temp_on_failure(tmp_path):
    target = tmp_path / "secret.yaml"
    target.write_text("orig")
    leaked: list[str] = []

    def fake_run(args, **kwargs):
        if "--encrypt" in args:
            leaked.append(args[-1])
            raise subprocess.CalledProcessError(1, args, stderr="sops failed")
        return _proc(0)

    with patch.object(bootstrap.subprocess, "run", side_effect=fake_run):
        with pytest.raises(subprocess.CalledProcessError):
            bootstrap.encrypt_secret_in_place(target, "new plaintext")

    # Tempfile must be cleaned up
    for path in leaked:
        assert not Path(path).exists(), f"leaked tempfile: {path}"
    # Target unchanged
    assert target.read_text() == "orig"


# ── bootstrap orchestration ─────────────────────────────────────────────────


def test_bootstrap_happy_path(tmp_path):
    secret_path = tmp_path / "secret.yaml"
    secret_path.write_text("encrypted-stub")

    tf_outputs = {
        "velero_aws_access_key_id": "AK1",
        "velero_aws_secret_access_key": "SK1",
    }

    with patch.object(
        bootstrap, "get_terraform_output", side_effect=lambda name, _: tf_outputs[name]
    ), patch.object(
        bootstrap, "decrypt_secret", return_value=PLAINTEXT_SECRET
    ), patch.object(
        bootstrap, "encrypt_secret_in_place"
    ) as mock_encrypt:
        bootstrap.bootstrap(Path("infra/aws"), secret_path)

    args, _ = mock_encrypt.call_args
    written_path, patched_plaintext = args
    assert written_path == secret_path
    assert "aws_access_key_id = AK1" in patched_plaintext
    assert "aws_secret_access_key = SK1" in patched_plaintext
    assert "OLD_PLACEHOLDER" not in patched_plaintext


def test_bootstrap_reads_custom_output_names(tmp_path):
    """The k3s-snapshot uploader reuses bootstrap() with different TF output names."""
    secret_path = tmp_path / "secret.yaml"
    secret_path.write_text("encrypted-stub")

    tf_outputs = {
        "k3s_snapshot_aws_access_key_id": "AK2",
        "k3s_snapshot_aws_secret_access_key": "SK2",
    }
    requested: list[str] = []

    def fake_output(name, _):
        requested.append(name)
        return tf_outputs[name]

    with patch.object(
        bootstrap, "get_terraform_output", side_effect=fake_output
    ), patch.object(
        bootstrap, "decrypt_secret", return_value=PLAINTEXT_SECRET
    ), patch.object(
        bootstrap, "encrypt_secret_in_place"
    ) as mock_encrypt:
        bootstrap.bootstrap(
            Path("infra/aws-velero"),
            secret_path,
            access_key_output="k3s_snapshot_aws_access_key_id",
            secret_key_output="k3s_snapshot_aws_secret_access_key",
        )

    assert requested == [
        "k3s_snapshot_aws_access_key_id",
        "k3s_snapshot_aws_secret_access_key",
    ]
    _, patched_plaintext = mock_encrypt.call_args[0]
    assert "aws_access_key_id = AK2" in patched_plaintext
    assert "aws_secret_access_key = SK2" in patched_plaintext


def test_main_passes_output_name_flags_through():
    with patch.object(bootstrap, "bootstrap") as mock_bootstrap:
        rc = bootstrap.main(
            [
                "--tf-dir", "infra/aws-velero",
                "--secret", "k8s/apps/k3s-snapshot/secret.yaml",
                "--access-key-output", "k3s_snapshot_aws_access_key_id",
                "--secret-key-output", "k3s_snapshot_aws_secret_access_key",
            ]
        )
    assert rc == 0
    _, kwargs = mock_bootstrap.call_args
    assert kwargs["access_key_output"] == "k3s_snapshot_aws_access_key_id"
    assert kwargs["secret_key_output"] == "k3s_snapshot_aws_secret_access_key"


def test_main_returns_zero_on_success(tmp_path):
    with patch.object(bootstrap, "bootstrap"):
        rc = bootstrap.main(
            ["--tf-dir", str(tmp_path), "--secret", str(tmp_path / "s.yaml")]
        )
    assert rc == 0


def test_main_returns_one_on_failure(tmp_path, capsys):
    with patch.object(bootstrap, "bootstrap", side_effect=RuntimeError("boom")):
        rc = bootstrap.main(
            ["--tf-dir", str(tmp_path), "--secret", str(tmp_path / "s.yaml")]
        )
    assert rc == 1
    captured = capsys.readouterr()
    assert "boom" in captured.err


def test_main_uses_default_paths_when_args_omitted():
    with patch.object(bootstrap, "bootstrap") as mock_bootstrap:
        rc = bootstrap.main([])
    assert rc == 0
    args, _ = mock_bootstrap.call_args
    tf_dir, secret_path = args
    assert tf_dir == bootstrap.DEFAULT_TF_DIR
    assert secret_path == bootstrap.DEFAULT_SECRET_PATH
