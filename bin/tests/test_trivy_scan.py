"""Tests for bin/trivy_scan.py — image extraction, dedupe, severity filter, exit codes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import trivy_scan  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────────


DEPLOYMENT_YAML = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alpha
spec:
  template:
    spec:
      initContainers:
        - name: init
          image: busybox:1.36
      containers:
        - name: main
          image: nginx:1.25
        - name: sidecar
          image: nginx:1.25
"""

DAEMONSET_YAML = """\
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: beta
spec:
  template:
    spec:
      containers:
        - name: agent
          image: prom/node-exporter:v1.7.0
"""

CRONJOB_YAML = """\
apiVersion: batch/v1
kind: CronJob
metadata:
  name: gamma
spec:
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: cleanup
              image: bitnami/kubectl:1.30
"""

POD_YAML = """\
apiVersion: v1
kind: Pod
metadata:
  name: probe
spec:
  containers:
    - name: probe
      image: curlimages/curl:8.5.0
"""

SOPS_YAML = """\
apiVersion: v1
kind: Secret
metadata: {name: secret}
sops:
  age: encrypted-blob
"""

CONFIGMAP_YAML = """\
apiVersion: v1
kind: ConfigMap
metadata: {name: cm}
data: {foo: bar}
"""


# ── extract_images ──────────────────────────────────────────────────────────


def test_extract_images_deployment_with_init_and_sidecar_dedupes():
    images = trivy_scan.extract_images(DEPLOYMENT_YAML)
    # nginx:1.25 appears twice (sidecar + main), dedupe
    assert images == ["busybox:1.36", "nginx:1.25"]


def test_extract_images_daemonset():
    assert trivy_scan.extract_images(DAEMONSET_YAML) == ["prom/node-exporter:v1.7.0"]


def test_extract_images_cronjob_walks_jobtemplate():
    assert trivy_scan.extract_images(CRONJOB_YAML) == ["bitnami/kubectl:1.30"]


def test_extract_images_pod():
    assert trivy_scan.extract_images(POD_YAML) == ["curlimages/curl:8.5.0"]


def test_extract_images_skips_sops_encrypted_doc():
    combined = SOPS_YAML + "---\n" + DEPLOYMENT_YAML
    images = trivy_scan.extract_images(combined)
    assert "secret" not in images
    assert "nginx:1.25" in images


def test_extract_images_skips_non_workload_kinds():
    assert trivy_scan.extract_images(CONFIGMAP_YAML) == []


def test_extract_images_handles_empty_input():
    assert trivy_scan.extract_images("") == []


def test_extract_images_dedupes_across_multiple_docs():
    combined = DEPLOYMENT_YAML + "---\n" + DAEMONSET_YAML + "---\n" + DEPLOYMENT_YAML
    images = trivy_scan.extract_images(combined)
    # busybox:1.36, nginx:1.25, prom/node-exporter:v1.7.0
    assert images == sorted(["busybox:1.36", "nginx:1.25", "prom/node-exporter:v1.7.0"])


def test_extract_images_handles_container_without_image_field():
    yaml_doc = """\
apiVersion: apps/v1
kind: Deployment
metadata: {name: x}
spec:
  template:
    spec:
      containers:
        - name: noimage
"""
    assert trivy_scan.extract_images(yaml_doc) == []


# ── has_blocking_vulns / summarize_report ───────────────────────────────────


def _report_with(severity_fix_pairs):
    """Build a fake trivy report with given (severity, has_fix) tuples."""
    vulns = []
    for sev, has_fix in severity_fix_pairs:
        v = {"Severity": sev}
        if has_fix:
            v["FixedVersion"] = "1.2.3"
        vulns.append(v)
    return {"Results": [{"Vulnerabilities": vulns}]}


def test_has_blocking_vulns_critical_with_fix_blocks():
    assert trivy_scan.has_blocking_vulns(_report_with([("CRITICAL", True)])) is True


def test_has_blocking_vulns_high_with_fix_blocks():
    assert trivy_scan.has_blocking_vulns(_report_with([("HIGH", True)])) is True


def test_has_blocking_vulns_high_without_fix_does_not_block():
    assert trivy_scan.has_blocking_vulns(_report_with([("HIGH", False)])) is False


def test_has_blocking_vulns_medium_with_fix_does_not_block():
    assert trivy_scan.has_blocking_vulns(_report_with([("MEDIUM", True)])) is False


def test_has_blocking_vulns_empty_report():
    assert trivy_scan.has_blocking_vulns({"Results": []}) is False


def test_has_blocking_vulns_missing_results_key():
    assert trivy_scan.has_blocking_vulns({}) is False


def test_summarize_report_counts_only_fixable():
    report = _report_with(
        [("HIGH", True), ("HIGH", False), ("CRITICAL", True), ("LOW", True)]
    )
    summary = trivy_scan.summarize_report("img:latest", report)
    assert summary == {
        "image": "img:latest",
        "blocking": {"HIGH": 1, "CRITICAL": 1},
        "blocked": True,
    }


def test_summarize_report_clean():
    summary = trivy_scan.summarize_report("img:clean", {"Results": []})
    assert summary["blocked"] is False
    assert summary["blocking"] == {"HIGH": 0, "CRITICAL": 0}


# ── sanitize_image_name ─────────────────────────────────────────────────────


def test_sanitize_image_name_replaces_slashes_and_colons():
    assert (
        trivy_scan.sanitize_image_name("ghcr.io/example/app:v1.2.3")
        == "ghcr.io_example_app_v1.2.3"
    )


def test_sanitize_image_name_keeps_safe_chars():
    assert trivy_scan.sanitize_image_name("nginx_1-25.0") == "nginx_1-25.0"


def test_sanitize_image_name_replaces_at_and_digest():
    safe = trivy_scan.sanitize_image_name("img@sha256:abc123")
    assert "@" not in safe and ":" not in safe


# ── scan_all orchestration (mocked subprocess) ──────────────────────────────


def test_scan_all_clean_returns_zero(tmp_path):
    rendered = DEPLOYMENT_YAML  # 2 images
    clean_report = {"Results": []}

    with patch.object(trivy_scan, "run_kustomize", return_value=rendered), patch.object(
        trivy_scan, "run_trivy", return_value=clean_report
    ) as mock_trivy:
        exit_code, summaries = trivy_scan.scan_all("k8s/apps", tmp_path)

    assert exit_code == 0
    assert len(summaries) == 2
    assert all(s["blocked"] is False for s in summaries)
    assert mock_trivy.call_count == 2
    # summary.json is persisted
    assert (tmp_path / "summary.json").exists()
    persisted = json.loads((tmp_path / "summary.json").read_text())
    assert len(persisted) == 2


def test_scan_all_one_dirty_image_returns_one(tmp_path):
    rendered = DEPLOYMENT_YAML
    clean = {"Results": []}
    dirty = _report_with([("CRITICAL", True)])

    # First call returns dirty, second returns clean
    with patch.object(trivy_scan, "run_kustomize", return_value=rendered), patch.object(
        trivy_scan, "run_trivy", side_effect=[dirty, clean]
    ):
        exit_code, summaries = trivy_scan.scan_all("k8s/apps", tmp_path)

    assert exit_code == 1
    blocked = [s for s in summaries if s["blocked"]]
    assert len(blocked) == 1


def test_scan_all_no_images_short_circuits(tmp_path):
    with patch.object(
        trivy_scan, "run_kustomize", return_value=CONFIGMAP_YAML
    ), patch.object(trivy_scan, "run_trivy") as mock_trivy:
        exit_code, summaries = trivy_scan.scan_all("k8s/apps", tmp_path)
    assert exit_code == 0
    assert summaries == []
    mock_trivy.assert_not_called()


# ── main / argparse ─────────────────────────────────────────────────────────


def test_main_default_args_returns_exit_code(tmp_path, capsys):
    with patch.object(trivy_scan, "scan_all", return_value=(0, [])) as mock_scan:
        rc = trivy_scan.main(["--output-dir", str(tmp_path)])
    assert rc == 0
    mock_scan.assert_called_once()


def test_main_advisory_mode_returns_zero_even_with_findings(tmp_path):
    blocked_summary = [
        {"image": "x", "blocked": True, "blocking": {"HIGH": 1, "CRITICAL": 0}}
    ]
    with patch.object(trivy_scan, "scan_all", return_value=(1, blocked_summary)):
        rc = trivy_scan.main(["--output-dir", str(tmp_path)])
    assert rc == 0  # advisory by default — does not break build


def test_main_strict_mode_propagates_nonzero_exit(tmp_path):
    blocked_summary = [
        {"image": "x", "blocked": True, "blocking": {"HIGH": 1, "CRITICAL": 0}}
    ]
    with patch.object(trivy_scan, "scan_all", return_value=(1, blocked_summary)):
        rc = trivy_scan.main(["--output-dir", str(tmp_path), "--strict"])
    assert rc == 1


def test_main_strict_mode_with_clean_scan_returns_zero(tmp_path):
    with patch.object(trivy_scan, "scan_all", return_value=(0, [])):
        rc = trivy_scan.main(["--output-dir", str(tmp_path), "--strict"])
    assert rc == 0


# ── subprocess wrappers (light coverage with patched subprocess) ────────────


def test_run_kustomize_invokes_kustomize_build():
    fake = MagicMock()
    fake.stdout = "rendered: yaml"
    with patch.object(trivy_scan.subprocess, "run", return_value=fake) as mock_run:
        out = trivy_scan.run_kustomize("k8s/apps")
    assert out == "rendered: yaml"
    args = mock_run.call_args.args[0]
    assert args[:2] == ["kustomize", "build"]
    assert args[2] == "k8s/apps"


def test_run_trivy_writes_report_and_returns_parsed(tmp_path):
    image = "nginx:1.25"
    expected_report = {"Results": [{"Vulnerabilities": []}]}

    def fake_run(cmd, **kwargs):
        # locate --output path argument and write our fake report
        out_idx = cmd.index("--output") + 1
        Path(cmd[out_idx]).write_text(json.dumps(expected_report))
        return MagicMock()

    with patch.object(trivy_scan.subprocess, "run", side_effect=fake_run):
        report = trivy_scan.run_trivy(image, tmp_path)

    assert report == expected_report
    assert (tmp_path / "nginx_1.25.json").exists()


# ── image allowlist ────────────────────────────────────────────────────────


def test_parse_image_allowlist_skips_comments_and_blank_lines():
    text = "\n".join(
        [
            "# heading comment",
            "",
            "grafana/grafana:10.2.3   # review-by: 2026-07-30",
            "  prom/prometheus:v2.45.0",  # leading whitespace tolerated
            "# trailing comment line",
            "",
        ]
    )
    parsed = trivy_scan.parse_image_allowlist(text)
    assert parsed == {"grafana/grafana:10.2.3", "prom/prometheus:v2.45.0"}


def test_parse_image_allowlist_empty_input_returns_empty_set():
    assert trivy_scan.parse_image_allowlist("") == set()


def test_load_allowlist_returns_empty_set_when_file_missing(tmp_path):
    assert trivy_scan.load_allowlist(tmp_path / "nope.txt") == set()


def test_load_allowlist_parses_existing_file(tmp_path):
    f = tmp_path / "allowed.txt"
    f.write_text("alpha:1\nbeta:2  # comment\n")
    assert trivy_scan.load_allowlist(f) == {"alpha:1", "beta:2"}


def test_scan_all_allowlisted_image_does_not_block(tmp_path):
    rendered = "kind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n        - name: x\n          image: vulnerable:1.0\n"
    blocking_report = {
        "Results": [
            {
                "Vulnerabilities": [
                    {"Severity": "CRITICAL", "FixedVersion": "1.1"},
                    {"Severity": "HIGH", "FixedVersion": "1.1"},
                ]
            }
        ]
    }
    with patch.object(trivy_scan, "run_kustomize", return_value=rendered), patch.object(
        trivy_scan, "run_trivy", return_value=blocking_report
    ):
        rc, summaries = trivy_scan.scan_all(
            "k8s/apps", tmp_path, allowlist={"vulnerable:1.0"}
        )
    assert rc == 0  # allowlisted image does not break the build
    assert summaries[0]["allowlisted"] is True
    assert summaries[0]["blocked"] is True  # finding still reported


def test_scan_all_non_allowlisted_image_still_blocks(tmp_path):
    rendered = "kind: Deployment\nspec:\n  template:\n    spec:\n      containers:\n        - name: x\n          image: vulnerable:1.0\n"
    blocking_report = {
        "Results": [
            {"Vulnerabilities": [{"Severity": "CRITICAL", "FixedVersion": "1.1"}]}
        ]
    }
    with patch.object(trivy_scan, "run_kustomize", return_value=rendered), patch.object(
        trivy_scan, "run_trivy", return_value=blocking_report
    ):
        rc, summaries = trivy_scan.scan_all("k8s/apps", tmp_path, allowlist=set())
    assert rc == 1
    assert summaries[0].get("allowlisted") is False
