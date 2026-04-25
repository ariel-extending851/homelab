"""Tests for bin/update_versions.py — pure helpers, file updaters, and scanner logic."""

import io
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update_versions as uv  # noqa: E402


# ── _version_key ──────────────────────────────────────────────────────────────

class TestVersionKey:
    def test_plain_semver(self):
        assert uv._version_key("10.2.3") == (10, 2, 3, 0)

    def test_v_prefix_stripped(self):
        assert uv._version_key("v2.45.0") == (2, 45, 0, 0)

    def test_linuxserver_ls_suffix(self):
        assert uv._version_key("5.0.3-r0-ls279") == (5, 0, 3, 279)

    def test_linuxserver_ls_tiebreaker(self):
        assert uv._version_key("5.0.3-r0-ls280") > uv._version_key("5.0.3-r0-ls279")

    def test_four_part_version(self):
        assert uv._version_key("2.3.5.5327-ls142") == (2, 3, 5, 5327, 142)

    def test_major_beats_minor(self):
        assert uv._version_key("6.0.0") > uv._version_key("5.99.99")


# ── is_newer ──────────────────────────────────────────────────────────────────

class TestIsNewer:
    def test_newer_major(self):
        assert uv.is_newer("6.0.0", "5.82.0")

    def test_newer_minor(self):
        assert uv.is_newer("2.9.0", "2.8.0")

    def test_newer_patch(self):
        assert uv.is_newer("v2.45.1", "v2.45.0")

    def test_same_version(self):
        assert not uv.is_newer("10.2.3", "10.2.3")

    def test_older_version(self):
        assert not uv.is_newer("10.2.2", "10.2.3")

    def test_v_prefix_ignored(self):
        assert uv.is_newer("v3.0.0", "2.9.9")

    def test_linuxserver_ls_bump(self):
        assert uv.is_newer("5.0.3-r0-ls280", "5.0.3-r0-ls279")


# ── _is_stable_tag ────────────────────────────────────────────────────────────

class TestIsStableTag:
    def test_accepts_semver(self):
        assert uv._is_stable_tag("10.2.3")

    def test_accepts_v_prefixed(self):
        assert uv._is_stable_tag("v2.45.0")

    def test_rejects_latest(self):
        assert not uv._is_stable_tag("latest")

    def test_rejects_edge(self):
        assert not uv._is_stable_tag("edge")

    def test_rejects_nightly(self):
        assert not uv._is_stable_tag("nightly")

    def test_rejects_main(self):
        assert not uv._is_stable_tag("main")

    def test_rejects_alpha(self):
        assert not uv._is_stable_tag("v2.0.0-alpha.1")

    def test_rejects_rc(self):
        assert not uv._is_stable_tag("v3.0.0rc1")

    def test_rejects_bare_sha(self):
        assert not uv._is_stable_tag("a3f4b2c1d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4")

    def test_rejects_empty(self):
        assert not uv._is_stable_tag("")

    def test_accepts_linuxserver(self):
        assert uv._is_stable_tag("5.0.3-r0-ls279")


# ── _best_tag ─────────────────────────────────────────────────────────────────

class TestBestTag:
    def test_picks_highest_semver(self):
        tags = ["v2.44.0", "v2.45.0", "v2.43.1", "latest"]
        assert uv._best_tag(tags, r"^v?\d+\.\d+(\.\d+)*$") == "v2.45.0"

    def test_empty_list(self):
        assert uv._best_tag([], r"^v?\d+\.\d+(\.\d+)*$") == ""

    def test_all_unstable(self):
        assert uv._best_tag(["latest", "nightly", "edge"], r"^v?\d+\.\d+(\.\d+)*$") == ""

    def test_pattern_filters_correctly(self):
        tags = ["2.3.5.5327-ls142", "2.3.5.5328-ls143", "latest", "develop"]
        best = uv._best_tag(tags, r"^\d+\.\d+\.\d+[\.\d]*-ls\d+$")
        assert best == "2.3.5.5328-ls143"


# ── constraint_needs_update ───────────────────────────────────────────────────

class TestConstraintNeedsUpdate:
    def test_major_bump_two_part(self):
        needs, new = uv.constraint_needs_update("~> 5.0", "6.36.0")
        assert needs is True
        assert new == "~> 6.0"

    def test_no_bump_same_major(self):
        needs, new = uv.constraint_needs_update("~> 5.0", "5.82.0")
        assert needs is False
        assert new == "~> 5.0"

    def test_minor_bump_three_part(self):
        needs, new = uv.constraint_needs_update("~> 0.7.0", "0.9.1")
        assert needs is True
        assert new == "~> 0.9.0"

    def test_no_bump_same_minor(self):
        needs, new = uv.constraint_needs_update("~> 0.7.0", "0.7.5")
        assert needs is False
        assert new == "~> 0.7.0"

    def test_minor_range_no_bump(self):
        # ~> 0.13 allows >= 0.13, < 1.0 — 0.17 is still within range
        needs, _ = uv.constraint_needs_update("~> 0.13", "0.17.0")
        assert needs is False

    def test_major_bump_from_zero(self):
        needs, new = uv.constraint_needs_update("~> 0.13", "1.2.0")
        assert needs is True
        assert new == "~> 1.0"

    def test_unrecognised_constraint(self):
        needs, new = uv.constraint_needs_update(">= 1.5.0", "2.0.0")
        assert needs is False
        assert new == ">= 1.5.0"


# ── update_ansible_requirements ───────────────────────────────────────────────

class TestUpdateAnsibleRequirements:
    def test_bumps_outdated_collection(self, tmp_path):
        req_file = tmp_path / "ansible" / "requirements.yml"
        req_file.parent.mkdir()
        req_file.write_text(textwrap.dedent("""\
            ---
            collections:
              - name: kubernetes.core
                version: ">=3.0.0"
              - name: community.sops
                version: ">=1.6.0"
        """))
        updates = [
            uv.VersionUpdate(
                name="ansible/kubernetes.core",
                current=">=3.0.0",
                latest=">=4.2.0",
                outdated=True,
                files=[req_file],
            )
        ]
        uv.update_ansible_requirements(updates, tmp_path)
        content = req_file.read_text()
        assert '">=4.2.0"' in content
        assert '">=1.6.0"' in content  # untouched

    def test_skips_up_to_date(self, tmp_path):
        req_file = tmp_path / "ansible" / "requirements.yml"
        req_file.parent.mkdir()
        original = textwrap.dedent("""\
            ---
            collections:
              - name: ansible.posix
                version: ">=1.5.0"
        """)
        req_file.write_text(original)
        updates = [
            uv.VersionUpdate(
                name="ansible/ansible.posix",
                current=">=1.5.0",
                latest=">=1.5.0",
                outdated=False,
                files=[req_file],
            )
        ]
        uv.update_ansible_requirements(updates, tmp_path)
        assert req_file.read_text() == original


# ── update_terraform_files ────────────────────────────────────────────────────

class TestUpdateTerraformFiles:
    def _make_tf(self, tmp_path: Path, content: str) -> Path:
        f = tmp_path / "main.tf"
        f.write_text(content)
        return f

    def test_bumps_aws_provider(self, tmp_path):
        tf = self._make_tf(tmp_path, textwrap.dedent("""\
            required_providers {
              aws = {
                source  = "hashicorp/aws"
                version = "~> 5.0"
              }
            }
        """))
        updates = [
            uv.VersionUpdate(
                name="terraform/hashicorp/aws",
                current="~> 5.0",
                latest="~> 6.0",
                outdated=True,
                files=[tf],
            )
        ]
        uv.update_terraform_files(updates, tmp_path)
        assert '"~> 6.0"' in tf.read_text()

    def test_skips_not_outdated(self, tmp_path):
        original = textwrap.dedent("""\
            required_providers {
              random = {
                source  = "hashicorp/random"
                version = "~> 3.0"
              }
            }
        """)
        tf = self._make_tf(tmp_path, original)
        updates = [
            uv.VersionUpdate(
                name="terraform/hashicorp/random",
                current="~> 3.0",
                latest="~> 3.0",
                outdated=False,
                files=[tf],
            )
        ]
        uv.update_terraform_files(updates, tmp_path)
        assert tf.read_text() == original

    def test_bumps_three_part_constraint(self, tmp_path):
        tf = self._make_tf(tmp_path, textwrap.dedent("""\
            required_providers {
              sops = {
                source  = "carlpett/sops"
                version = "~> 0.7.0"
              }
            }
        """))
        updates = [
            uv.VersionUpdate(
                name="terraform/carlpett/sops",
                current="~> 0.7.0",
                latest="~> 0.9.0",
                outdated=True,
                files=[tf],
            )
        ]
        uv.update_terraform_files(updates, tmp_path)
        assert '"~> 0.9.0"' in tf.read_text()


# ── update_k8s_manifests ──────────────────────────────────────────────────────

class TestUpdateK8sManifests:
    def _make_deployment(self, tmp_path: Path, image_line: str) -> Path:
        apps = tmp_path / "k8s" / "apps" / "grafana"
        apps.mkdir(parents=True)
        f = apps / "deployment.yaml"
        f.write_text(f"spec:\n  containers:\n  - name: grafana\n    {image_line}\n")
        return f

    def test_bumps_image_tag(self, tmp_path):
        deploy = self._make_deployment(tmp_path, "image: grafana/grafana:10.2.3")
        updates = [
            uv.VersionUpdate(
                name="k8s/grafana/grafana",
                current="10.2.3",
                latest="11.5.0",
                outdated=True,
                files=[deploy],
            )
        ]
        uv.update_k8s_manifests(updates, tmp_path)
        assert "grafana/grafana:11.5.0" in deploy.read_text()

    def test_preserves_untouched_images(self, tmp_path):
        apps = tmp_path / "k8s" / "apps" / "mixed"
        apps.mkdir(parents=True)
        f = apps / "deployment.yaml"
        f.write_text(
            "containers:\n"
            "  - image: grafana/grafana:10.2.3\n"
            "  - image: prom/prometheus:v2.45.0\n"
        )
        updates = [
            uv.VersionUpdate(
                name="k8s/grafana/grafana",
                current="10.2.3",
                latest="11.5.0",
                outdated=True,
                files=[f],
            )
        ]
        uv.update_k8s_manifests(updates, tmp_path)
        content = f.read_text()
        assert "grafana/grafana:11.5.0" in content
        assert "prom/prometheus:v2.45.0" in content  # untouched


# ── _extract_tf_constraint ────────────────────────────────────────────────────

class TestExtractTfConstraint:
    def test_extracts_constraint(self):
        hcl = textwrap.dedent("""\
            aws = {
              source  = "hashicorp/aws"
              version = "~> 5.0"
            }
        """)
        assert uv._extract_tf_constraint("aws", hcl) == "~> 5.0"

    def test_returns_empty_when_not_found(self):
        assert uv._extract_tf_constraint("nonexistent", "source = hashicorp/aws") == ""

    def test_handles_three_part_constraint(self):
        hcl = 'source  = "carlpett/sops"\nversion = "~> 0.7.0"'
        assert uv._extract_tf_constraint("sops", hcl) == "~> 0.7.0"


# ── fetch helpers (mocked network) ───────────────────────────────────────────

class TestFetchGalaxyVersion:
    def test_extracts_highest_version(self):
        mock_response = {"highest_version": {"version": "4.2.0"}}
        with patch("update_versions.fetch_json", return_value=mock_response):
            assert uv.fetch_galaxy_version("kubernetes", "core") == "4.2.0"

    def test_raises_on_none_response(self):
        with patch("update_versions.fetch_json", return_value=None):
            with pytest.raises(RuntimeError, match="Galaxy API unreachable"):
                uv.fetch_galaxy_version("kubernetes", "core")

    def test_raises_on_missing_version(self):
        with patch("update_versions.fetch_json", return_value={"highest_version": {}}):
            with pytest.raises(RuntimeError, match="No version"):
                uv.fetch_galaxy_version("kubernetes", "core")


class TestFetchTfProviderVersion:
    def test_extracts_version(self):
        with patch("update_versions.fetch_json", return_value={"version": "6.36.0"}):
            assert uv.fetch_tf_provider_version("hashicorp", "aws") == "6.36.0"

    def test_raises_on_none(self):
        with patch("update_versions.fetch_json", return_value=None):
            with pytest.raises(RuntimeError, match="Terraform Registry unreachable"):
                uv.fetch_tf_provider_version("hashicorp", "aws")


class TestFetchDockerhubLatest:
    def test_picks_best_semver_tag(self):
        mock_data = {
            "results": [
                {"name": "latest"},
                {"name": "11.5.0"},
                {"name": "11.4.0"},
                {"name": "10.2.3"},
            ],
            "next": None,
        }
        with patch("update_versions.fetch_json", return_value=mock_data):
            result = uv.fetch_dockerhub_latest("grafana/grafana", r"^v?\d+\.\d+(\.\d+)*$")
        assert result == "11.5.0"

    def test_raises_when_no_stable_tag(self):
        mock_data = {"results": [{"name": "latest"}, {"name": "nightly"}], "next": None}
        with patch("update_versions.fetch_json", return_value=mock_data):
            with pytest.raises(RuntimeError, match="No stable"):
                uv.fetch_dockerhub_latest("repo/image", r"^v?\d+\.\d+(\.\d+)*$")


class TestFetchQuayLatest:
    def test_picks_best_tag(self):
        mock_data = {
            "tags": [
                {"name": "v0.24.0"},
                {"name": "v0.25.0"},
                {"name": "latest"},
            ]
        }
        with patch("update_versions.fetch_json", return_value=mock_data):
            result = uv.fetch_quay_latest(
                "prometheus/blackbox-exporter", r"^v?\d+\.\d+(\.\d+)*$"
            )
        assert result == "v0.25.0"


class TestFetchGithubRelease:
    def test_returns_tag_name(self):
        with patch("update_versions.fetch_json", return_value={"tag_name": "v3.5.0"}):
            assert uv.fetch_github_release_latest("***/***") == "v3.5.0"

    def test_raises_on_missing_tag(self):
        with patch("update_versions.fetch_json", return_value={"name": "release"}):
            with pytest.raises(RuntimeError, match="GitHub releases API unreachable"):
                uv.fetch_github_release_latest("owner/repo")


# ── _image_name / _current_tag helpers ───────────────────────────────────────

class TestImageHelpers:
    def test_image_name_strips_tag(self):
        assert uv._image_name("grafana/grafana:10.2.3") == "grafana/grafana"

    def test_image_name_no_tag(self):
        assert uv._image_name("busybox") == "busybox"

    def test_current_tag_extracts_tag(self):
        assert uv._current_tag("prom/prometheus:v2.45.0") == "v2.45.0"

    def test_current_tag_no_colon(self):
        assert uv._current_tag("busybox") == ""

    def test_current_tag_lscr(self):
        assert uv._current_tag("lscr.io/linuxserver/***:2.3.5.5327-ls142") == "2.3.5.5327-ls142"


# ── _latest_tag_for ───────────────────────────────────────────────────────────

class TestLatestTagFor:
    def _spec(self, registry, lookup, tag_pattern=r"^v?\d+\.\d+(\.\d+)*$"):
        return uv.ImageSpec(
            image_ref=f"some/image:1.0",
            registry=registry,
            lookup=lookup,
            tag_pattern=tag_pattern,
        )

    def test_dockerhub_route(self):
        spec = self._spec("dockerhub", "grafana/grafana")
        with patch("update_versions.fetch_dockerhub_latest", return_value="11.0.0") as m:
            assert uv._latest_tag_for(spec) == "11.0.0"
            m.assert_called_once_with("grafana/grafana", spec.tag_pattern)

    def test_quay_route(self):
        spec = self._spec("quay", "prometheus/node-exporter")
        with patch("update_versions.fetch_quay_latest", return_value="v1.8.0") as m:
            assert uv._latest_tag_for(spec) == "v1.8.0"
            m.assert_called_once_with("prometheus/node-exporter", spec.tag_pattern)

    def test_github_releases_route(self):
        spec = self._spec("github_releases", "***/***")
        with patch("update_versions.fetch_github_release_latest", return_value="v3.5.0") as m:
            assert uv._latest_tag_for(spec) == "v3.5.0"
            m.assert_called_once_with("***/***")

    def test_unknown_registry_raises(self):
        spec = self._spec("bogus", "owner/repo")
        with pytest.raises(RuntimeError, match="Unknown registry"):
            uv._latest_tag_for(spec)


# ── scan_ansible ──────────────────────────────────────────────────────────────

class TestScanAnsible:
    def _make_requirements(self, tmp_path: Path) -> Path:
        req = tmp_path / "ansible" / "requirements.yml"
        req.parent.mkdir(parents=True)
        req.write_text(textwrap.dedent("""\
            ---
            collections:
              - name: kubernetes.core
                version: ">=3.0.0"
              - name: community.sops
                version: ">=1.6.0"
              - name: community.general
                version: ">=8.0.0"
              - name: ansible.posix
                version: ">=1.5.0"
        """))
        return req

    def test_detects_outdated_collection(self, tmp_path):
        self._make_requirements(tmp_path)

        def fake_galaxy(ns, name):
            return {"kubernetes": {"core": "4.2.0"}, "community": {"sops": "1.6.0",
                    "general": "8.0.0"}, "ansible": {"posix": "1.5.0"}}[ns][name]

        with patch("update_versions.fetch_galaxy_version", side_effect=fake_galaxy):
            updates = uv.scan_ansible(tmp_path)

        k8s = next(u for u in updates if "kubernetes.core" in u.name)
        assert k8s.outdated is True
        assert k8s.latest == ">=4.2.0"

    def test_up_to_date_not_flagged(self, tmp_path):
        self._make_requirements(tmp_path)

        # Return the exact minimum pinned for each collection so none appear outdated
        minimums = {
            ("kubernetes", "core"): "3.0.0",
            ("community", "sops"): "1.6.0",
            ("community", "general"): "8.0.0",
            ("ansible", "posix"): "1.5.0",
        }
        with patch("update_versions.fetch_galaxy_version",
                   side_effect=lambda ns, name: minimums[(ns, name)]):
            updates = uv.scan_ansible(tmp_path)

        assert all(not u.outdated for u in updates)

    def test_api_error_recorded(self, tmp_path):
        self._make_requirements(tmp_path)

        with patch("update_versions.fetch_galaxy_version",
                   side_effect=RuntimeError("Galaxy API unreachable")):
            updates = uv.scan_ansible(tmp_path)

        assert all(u.error for u in updates)
        assert all(not u.outdated for u in updates)


# ── scan_terraform ────────────────────────────────────────────────────────────

class TestScanTerraform:
    def _make_tf_files(self, tmp_path: Path) -> None:
        for path, content in [
            ("infra/aws/main.tf", textwrap.dedent("""\
                required_providers {
                  aws = {
                    source  = "hashicorp/aws"
                    version = "~> 5.0"
                  }
                  sops = {
                    source  = "carlpett/sops"
                    version = "~> 0.7.0"
                  }
                  tailscale = {
                    source  = "tailscale/tailscale"
                    version = "~> 0.13"
                  }
                }
            """)),
            ("infra/aws-backend/main.tf", textwrap.dedent("""\
                required_providers {
                  aws = {
                    source  = "hashicorp/aws"
                    version = "~> 5.0"
                  }
                  random = {
                    source  = "hashicorp/random"
                    version = "~> 3.0"
                  }
                }
            """)),
            ("infra/aws/modules/scheduler/versions.tf", textwrap.dedent("""\
                required_providers {
                  archive = {
                    source  = "hashicorp/archive"
                    version = "~> 2.0"
                  }
                }
            """)),
        ]:
            f = tmp_path / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)

        # Create remaining stub files so the scanner finds them
        for stub in [
            "infra/aws-oidc/versions.tf",
            "infra/aws/modules/compute/versions.tf",
            "infra/aws/modules/network/versions.tf",
        ]:
            p = tmp_path / stub
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                'required_providers {\n  aws = {\n'
                '    source  = "hashicorp/aws"\n'
                '    version = "~> 5.0"\n  }\n}\n'
            )

    def test_detects_major_bump(self, tmp_path):
        self._make_tf_files(tmp_path)

        def fake_version(ns, prov):
            return {"hashicorp/aws": "6.36.0", "carlpett/sops": "0.7.2",
                    "tailscale/tailscale": "0.15.0", "hashicorp/random": "3.6.0",
                    "hashicorp/archive": "2.4.0"}[f"{ns}/{prov}"]

        with patch("update_versions.fetch_tf_provider_version", side_effect=lambda ns, p: fake_version(ns, p)):
            updates = uv.scan_terraform(tmp_path)

        aws = next(u for u in updates if "hashicorp/aws" in u.name)
        assert aws.outdated is True
        assert aws.latest == "~> 6.0"

    def test_no_update_within_constraint(self, tmp_path):
        self._make_tf_files(tmp_path)

        with patch("update_versions.fetch_tf_provider_version", return_value="5.82.0"):
            updates = uv.scan_terraform(tmp_path)

        aws = next(u for u in updates if "hashicorp/aws" in u.name)
        assert aws.outdated is False

    def test_api_error_recorded(self, tmp_path):
        self._make_tf_files(tmp_path)

        with patch("update_versions.fetch_tf_provider_version",
                   side_effect=RuntimeError("Registry down")):
            updates = uv.scan_terraform(tmp_path)

        assert all(u.error for u in updates)


# ── scan_k8s ─────────────────────────────────────────────────────────────────

class TestScanK8s:
    def _make_k8s_files(self, tmp_path: Path) -> None:
        deploy = tmp_path / "k8s" / "apps" / "grafana" / "deployment.yaml"
        deploy.parent.mkdir(parents=True)
        deploy.write_text(
            "spec:\n  containers:\n  - name: grafana\n"
            "    image: grafana/grafana:10.2.3\n"
        )

    def test_detects_outdated_image(self, tmp_path):
        self._make_k8s_files(tmp_path)

        with patch("update_versions._latest_tag_for") as mock_latest:
            mock_latest.return_value = "11.5.0"
            updates = uv.scan_k8s(tmp_path)

        grafana = next((u for u in updates if "grafana/grafana" in u.name), None)
        assert grafana is not None
        assert grafana.outdated is True
        assert grafana.latest == "11.5.0"

    def test_skipped_images_not_fetched(self, tmp_path):
        self._make_k8s_files(tmp_path)

        with patch("update_versions._latest_tag_for") as mock_latest:
            mock_latest.return_value = "1.0.0"
            updates = uv.scan_k8s(tmp_path)

        skipped = [u for u in updates if u.skip_reason]
        assert len(skipped) > 0
        # _latest_tag_for should never be called for skipped specs
        for u in skipped:
            assert u.latest == ""

    def test_api_error_recorded(self, tmp_path):
        self._make_k8s_files(tmp_path)

        with patch("update_versions._latest_tag_for",
                   side_effect=RuntimeError("API down")):
            updates = uv.scan_k8s(tmp_path)

        errored = [u for u in updates if u.error]
        assert len(errored) > 0


# ── git helpers ───────────────────────────────────────────────────────────────

class TestGitHelpers:
    def test_create_branch_new(self, tmp_path):
        def fake_run(args, **kwargs):
            r = MagicMock()
            if args[:2] == ["git", "show-ref"]:
                r.returncode = 1  # branch doesn't exist
            else:
                r.returncode = 0
            return r

        with patch("update_versions.subprocess.run", side_effect=fake_run):
            result = uv.git_create_branch("chore/test-branch", tmp_path)
        assert result is True

    def test_create_branch_existing(self, tmp_path):
        def fake_run(args, **kwargs):
            r = MagicMock()
            r.returncode = 0  # branch exists AND checkout succeeds
            return r

        with patch("update_versions.subprocess.run", side_effect=fake_run):
            result = uv.git_create_branch("chore/test-branch", tmp_path)
        assert result is True

    def test_create_branch_failure(self, tmp_path, capsys):
        def fake_run(args, **kwargs):
            r = MagicMock()
            if args[:2] == ["git", "show-ref"]:
                r.returncode = 1
            else:
                r.returncode = 1
                r.stderr = "fatal: something went wrong"
            return r

        with patch("update_versions.subprocess.run", side_effect=fake_run):
            result = uv.git_create_branch("chore/bad", tmp_path)
        assert result is False

    def test_stage_files(self, tmp_path):
        called_with = []

        def fake_run(args, **kwargs):
            called_with.append(args)
            r = MagicMock()
            r.returncode = 0
            return r

        files = [tmp_path / "a.yaml", tmp_path / "b.tf"]
        with patch("update_versions.subprocess.run", side_effect=fake_run):
            uv.git_stage_files(files, tmp_path)

        staged = [a for a in called_with if "add" in a]
        assert len(staged) == 2


# ── run_lint ─────────────────────────────────────────────────────────────────

class TestRunLint:
    def _ok(self):
        r = MagicMock()
        r.returncode = 0
        r.stderr = ""
        r.stdout = ""
        return r

    def _fail(self, stderr="err"):
        r = MagicMock()
        r.returncode = 1
        r.stderr = stderr
        r.stdout = stderr
        return r

    def test_kustomize_pass(self, tmp_path):
        (tmp_path / "k8s" / "apps").mkdir(parents=True)
        with patch("update_versions.shutil.which", return_value="/usr/bin/kustomize"), \
             patch("update_versions.subprocess.run", return_value=self._ok()):
            results = uv.run_lint(tmp_path)
        kustomize_result = next(r for r in results if "kustomize" in r)
        assert "PASS" in kustomize_result

    def test_kustomize_fail(self, tmp_path):
        with patch("update_versions.shutil.which", return_value="/usr/bin/kustomize"), \
             patch("update_versions.subprocess.run", return_value=self._fail("bad manifest")):
            results = uv.run_lint(tmp_path)
        kustomize_result = next(r for r in results if "kustomize" in r)
        assert "FAIL" in kustomize_result

    def test_kustomize_not_found(self, tmp_path):
        with patch("update_versions.shutil.which", return_value=None):
            results = uv.run_lint(tmp_path)
        kustomize_result = next(r for r in results if "kustomize" in r)
        assert "SKIP" in kustomize_result

    def test_terraform_pass(self, tmp_path):
        for d in ["infra/aws"]:
            (tmp_path / d).mkdir(parents=True)

        def which_side(cmd):
            return f"/usr/bin/{cmd}" if cmd in ("kustomize", "terraform", "yamllint") else None

        with patch("update_versions.shutil.which", side_effect=which_side), \
             patch("update_versions.subprocess.run", return_value=self._ok()):
            results = uv.run_lint(tmp_path)

        tf_results = [r for r in results if "terraform fmt" in r]
        assert any("PASS" in r for r in tf_results)

    def test_yamllint_pass(self, tmp_path):
        req = tmp_path / "ansible" / "requirements.yml"
        req.parent.mkdir(parents=True)
        req.write_text("---\ncollections: []\n")

        def which_side(cmd):
            return f"/usr/bin/{cmd}" if cmd == "yamllint" else None

        with patch("update_versions.shutil.which", side_effect=which_side), \
             patch("update_versions.subprocess.run", return_value=self._ok()):
            results = uv.run_lint(tmp_path)

        yamllint_result = next(r for r in results if "yamllint" in r)
        assert "PASS" in yamllint_result


# ── print_report ──────────────────────────────────────────────────────────────

class TestPrintReport:
    def _make_updates(self, outdated=False):
        return [
            uv.VersionUpdate(
                name="ansible/kubernetes.core",
                current=">=3.0.0",
                latest=">=4.2.0" if outdated else ">=3.0.0",
                outdated=outdated,
            )
        ]

    def test_all_up_to_date_returns_zero(self, capsys):
        rc = uv.print_report(
            self._make_updates(False), [], [], [], "chore/test", dry_run=False
        )
        assert rc == 0
        assert "up-to-date" in capsys.readouterr().out

    def test_outdated_returns_one(self, capsys):
        rc = uv.print_report(
            self._make_updates(True), [], [], [], "chore/test", dry_run=False
        )
        assert rc == 1

    def test_dry_run_shows_message(self, capsys):
        uv.print_report(
            self._make_updates(True), [], [], [], "chore/test", dry_run=True
        )
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_errors_reported(self, capsys):
        updates = [uv.VersionUpdate(
            name="k8s/img", current="1.0", latest="", outdated=False,
            error="API down",
        )]
        uv.print_report([], [], updates, [], "chore/test", dry_run=False)
        out = capsys.readouterr().out
        assert "API down" in out

    def test_skipped_shown(self, capsys):
        updates = [uv.VersionUpdate(
            name="k8s/golink", current="main", latest="", outdated=False,
            skip_reason="digest-pinned",
        )]
        uv.print_report([], [], updates, [], "chore/test", dry_run=False)
        assert "digest-pinned" in capsys.readouterr().out

    def test_lint_results_shown(self, capsys):
        uv.print_report([], [], [], ["PASS kustomize build"], "chore/test", dry_run=False)
        assert "kustomize" in capsys.readouterr().out


# ── fetch_json ────────────────────────────────────────────────────────────────

class TestFetchJson:
    def test_returns_none_on_error(self):
        with patch("update_versions.urllib.request.urlopen",
                   side_effect=Exception("network error")):
            assert uv.fetch_json("http://example.com/api") is None

    def test_parses_json_response(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"version": "1.2.3"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("update_versions.urllib.request.urlopen", return_value=mock_resp):
            result = uv.fetch_json("http://example.com/api")
        assert result == {"version": "1.2.3"}


# ── main ──────────────────────────────────────────────────────────────────────

class TestMain:
    def _up_to_date(self):
        return [uv.VersionUpdate(name="x", current="1.0", latest="1.0", outdated=False)]

    def _outdated(self):
        return [uv.VersionUpdate(
            name="k8s/grafana/grafana", current="10.2.3", latest="11.5.0",
            outdated=True, files=[],
        )]

    def test_exits_zero_when_all_current(self, capsys):
        with patch("update_versions.scan_ansible", return_value=self._up_to_date()), \
             patch("update_versions.scan_terraform", return_value=self._up_to_date()), \
             patch("update_versions.scan_k8s", return_value=self._up_to_date()):
            rc = uv.main.__wrapped__() if hasattr(uv.main, "__wrapped__") else \
                 self._call_main([])
        assert rc == 0

    def _call_main(self, argv):
        import sys as _sys
        old = _sys.argv
        _sys.argv = ["update_versions.py"] + argv
        try:
            return uv.main()
        finally:
            _sys.argv = old

    def test_dry_run_no_file_changes(self, tmp_path, capsys):
        with patch("update_versions.scan_ansible", return_value=self._outdated()), \
             patch("update_versions.scan_terraform", return_value=[]), \
             patch("update_versions.scan_k8s", return_value=[]), \
             patch("update_versions.update_ansible_requirements") as mock_update, \
             patch("update_versions.git_create_branch") as mock_branch:
            rc = self._call_main(["--dry-run"])

        assert rc == 1
        mock_update.assert_not_called()
        mock_branch.assert_not_called()

    def test_component_flag_limits_scan(self, capsys):
        with patch("update_versions.scan_ansible", return_value=self._up_to_date()) as mock_a, \
             patch("update_versions.scan_terraform", return_value=[]) as mock_tf, \
             patch("update_versions.scan_k8s", return_value=[]) as mock_k8s:
            self._call_main(["--component", "ansible"])

        mock_a.assert_called_once()
        mock_tf.assert_not_called()
        mock_k8s.assert_not_called()

    def test_skip_git_flag(self, capsys):
        with patch("update_versions.scan_ansible", return_value=self._outdated()), \
             patch("update_versions.scan_terraform", return_value=[]), \
             patch("update_versions.scan_k8s", return_value=[]), \
             patch("update_versions.update_ansible_requirements"), \
             patch("update_versions.run_lint", return_value=[]), \
             patch("update_versions.git_create_branch") as mock_branch, \
             patch("update_versions.git_stage_files") as mock_stage:
            self._call_main(["--skip-git"])

        mock_branch.assert_not_called()
        mock_stage.assert_not_called()
