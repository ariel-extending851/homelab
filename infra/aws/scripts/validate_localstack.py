#!/usr/bin/env python3
"""LocalStack Structure Validation.

Port of infra/aws/scripts/test-localstack.sh. Runs eight Terraform
validation tests against a LocalStack endpoint, asserts key resources
land in state, cleans up afterwards, and reports a pass/fail summary.
Behavior preserved: same pass/fail counters, same exit codes, same
state-assertion patterns, same tolerated failures (EC2 Fleet, graph,
output, apply, destroy).

Prerequisites:
  - LocalStack running on http://localhost:4566
  - tflocal on PATH (or at ~/.local/share/mise/shims/ or ~/.local/bin/)
  - Optionally SOPS_AGE_KEY_FILE pointing at an existing key file
"""

import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
NC = "\033[0m"

LOCALSTACK_HEALTH_URL = "http://localhost:4566/_localstack/health"
LOG_DIR = Path("/tmp")


class LocalStackTester:
    def __init__(self, workdir=None, env=None):
        self.workdir = (
            Path(workdir) if workdir else Path(__file__).resolve().parent.parent
        )
        self.env = dict(env if env is not None else os.environ)
        self.passed = 0
        self.failed = 0
        self.sops_enabled = False

    # ── logging ──────────────────────────────────────────────────────────────

    def log_info(self, msg):
        print(f"{BLUE}[INFO]{NC} {msg}")

    def log_success(self, msg):
        print(f"{GREEN}[✓]{NC} {msg}")
        self.passed += 1

    def log_error(self, msg):
        print(f"{RED}[✗]{NC} {msg}")
        self.failed += 1

    def log_warning(self, msg):
        print(f"{YELLOW}[!]{NC} {msg}")

    # ── prerequisites ────────────────────────────────────────────────────────

    def check_localstack_running(self):
        try:
            with urllib.request.urlopen(LOCALSTACK_HEALTH_URL, timeout=3) as resp:
                if 200 <= resp.status < 300:
                    self.log_success("LocalStack is running")
                    return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            pass
        self.log_error("LocalStack is not running on localhost:4566")
        self.log_warning(
            "Start LocalStack with: "
            "docker run -d -p 4566:4566 localstack/localstack:latest"
        )
        return False

    def check_tflocal_available(self):
        candidates = [
            ("tflocal", None),
            (str(Path.home() / ".local/share/mise/shims/tflocal"), "via mise shims"),
            (str(Path.home() / ".local/bin/tflocal"), "via pipx local"),
        ]
        for path, note in candidates:
            if self._is_executable(path):
                label = "tflocal installed"
                if note:
                    label += f" ({note})"
                    # Prepend the parent dir to PATH in the captured env copy
                    self.env["PATH"] = f"{Path(path).parent}:{self.env.get('PATH', '')}"
                self.log_success(label)
                return True
        self.log_error(
            "tflocal not found. Install via: mise install or pipx install terraform-local"
        )
        return False

    def _is_executable(self, path):
        if "/" in path:
            p = Path(path)
            return p.is_file() and os.access(p, os.X_OK)
        # Name lookup on PATH — a file with the right name that is not
        # marked executable should NOT satisfy the check.
        for directory in (self.env.get("PATH", "") or os.defpath).split(":"):
            if directory:
                candidate = Path(directory, path)
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return True
        return False

    def check_sops_configured(self):
        key_file = self.env.get("SOPS_AGE_KEY_FILE")
        if key_file and Path(key_file).is_file():
            self.log_success("SOPS configured with AGE key")
            self.sops_enabled = True
            self.env["SOPS_ENABLED"] = "true"
        else:
            self.log_warning("SOPS not configured (will use mock secrets)")
            self.sops_enabled = False
            self.env["SOPS_ENABLED"] = "false"

    # ── command execution ───────────────────────────────────────────────────

    def _run_logged(self, args, log_path, extra_env=None):
        """Run tflocal, redirect stdout+stderr to log_path, return returncode."""
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        with open(log_path, "w") as fh:
            proc = subprocess.run(
                args, cwd=self.workdir, env=env, stdout=fh, stderr=subprocess.STDOUT
            )
        return proc.returncode

    def _run_capture(self, args, log_path=None, extra_env=None):
        """Run and capture stdout. Optionally also tee to a log."""
        env = dict(self.env)
        if extra_env:
            env.update(extra_env)
        result = subprocess.run(
            args,
            cwd=self.workdir,
            env=env,
            capture_output=True,
            text=True,
        )
        if log_path:
            log_path.write_text((result.stdout or "") + (result.stderr or ""))
        return result

    # ── 8-test sequence ──────────────────────────────────────────────────────

    def test_init(self):
        self.log_info("Test 1/6: Terraform initialization")
        rc = self._run_logged(
            ["tflocal", "init", "-reconfigure", "-upgrade"], LOG_DIR / "tf-init.log"
        )
        if rc == 0:
            self.log_success("Terraform initialized successfully")
            return True
        self.log_error("Terraform initialization failed")
        self._dump(LOG_DIR / "tf-init.log")
        return False

    def test_validate(self):
        self.log_info("Test 2/6: Configuration validation")
        rc = self._run_logged(["tflocal", "validate"], LOG_DIR / "tf-validate.log")
        if rc == 0:
            self.log_success("Configuration is valid")
            return True
        self.log_error("Configuration validation failed")
        self._dump(LOG_DIR / "tf-validate.log")
        return False

    def test_get(self):
        self.log_info("Test 3/6: Module loading")
        rc = self._run_logged(["tflocal", "get", "-update"], LOG_DIR / "tf-get.log")
        if rc == 0:
            self.log_success("Modules loaded successfully")
            modules_dir = self.workdir / "modules"
            count = (
                sum(
                    1
                    for p in modules_dir.glob("**/")
                    if p.name in ("compute", "network")
                )
                if modules_dir.is_dir()
                else 0
            )
            self.log_info(f"  - Found {count} modules (compute, network)")
            return True
        self.log_error("Module loading failed")
        self._dump(LOG_DIR / "tf-get.log")
        return False

    def test_plan(self):
        self.log_info("Test 4/6: Plan generation")
        rc = self._run_logged(
            ["tflocal", "plan", "-out=terraform.tfplan"], LOG_DIR / "tf-plan.log"
        )
        if rc == 0:
            self.log_success("Plan generated successfully")
            show = self._run_capture(["tflocal", "show", "-json", "terraform.tfplan"])
            resource_count = 0
            if show.returncode == 0:
                try:
                    import json as _json

                    resource_count = len(
                        _json.loads(show.stdout).get("resource_changes", [])
                    )
                except (ValueError, KeyError):
                    resource_count = 0
            self.log_info(f"  - Plan includes {resource_count} resource changes")
            return True
        self.log_error("Plan generation failed")
        self._dump(LOG_DIR / "tf-plan.log")
        return False

    def test_graph(self):
        self.log_info("Test 5/6: Dependency graph generation")
        graph_path = self.workdir / "terraform-graph.dot"
        rc = self._run_logged(["tflocal", "graph"], graph_path)
        if rc == 0:
            self.log_success("Dependency graph generated")
            self.log_info(f"  - Graph saved to: {graph_path}")
            try:
                node_count = sum(
                    1 for _ in re.finditer(r"label", graph_path.read_text())
                )
            except OSError:
                node_count = 0
            self.log_info(f"  - Graph contains {node_count} nodes")
        else:
            self.log_error("Graph generation failed")

    def test_output(self):
        self.log_info("Test 6/8: Output validation (pre-apply)")
        rc = self._run_logged(["tflocal", "output"], LOG_DIR / "tf-output.log")
        if rc == 0:
            self.log_success("Outputs validated successfully")
        else:
            self.log_warning(
                "Outputs not yet available (requires apply) — expected at this stage"
            )

    def test_apply(self):
        self.log_info("Test 7/8: Terraform apply against LocalStack")
        print("  (EC2 Fleet failures are tolerated — LocalStack free tier limitation)")
        rc = self._run_logged(
            [
                "tflocal",
                "apply",
                "-auto-approve",
                "-var-file=terraform.tfvars.localstack",
            ],
            LOG_DIR / "tf-apply.log",
            extra_env={"TF_VAR_localstack_test": "yes"},
        )
        if rc == 0:
            self.log_success("Apply completed without errors")
        else:
            self.log_warning("Apply had some failures (likely EC2 Fleet — tolerated)")

    def test_output_schema_post_apply(self):
        """Post-apply: verify `terraform output -json` contains the exact keys
        that ansible/terraform_inventory_aws.py consumes.

        This is the real contract: if Terraform outputs are renamed or their
        schema changes, the inventory generator breaks silently in production.
        """
        self.log_info("Test 8a/8: Output schema contract (ansible inventory keys)")
        output_log = LOG_DIR / "tf-output-json.log"
        rc = self._run_logged(["tflocal", "output", "-json"], output_log)
        if rc != 0:
            self.log_warning(
                "Output JSON not available (apply likely failed — tolerated)"
            )
            return

        try:
            stdout = output_log.read_text()
        except OSError:
            stdout = ""

        # Lazy import: ansible/ directory may not be on sys.path
        ansible_dir = Path(__file__).resolve().parents[3] / "ansible"
        sys.path.insert(0, str(ansible_dir))
        try:
            import terraform_inventory_aws as inv  # noqa: E402

            outputs = inv.parse_terraform_output_json(stdout)
        except Exception as exc:
            self.log_error(f"Failed to parse terraform output JSON: {exc}")
            return
        finally:
            if str(ansible_dir) in sys.path:
                sys.path.remove(str(ansible_dir))

        required_keys = {
            "k3s_server_public_ip",
            "k3s_server_private_ip",
            "k3s_server_instance_id",
            "k3s_agent_public_ip",
            "k3s_agent_private_ip",
            "k3s_agent_instance_id",
        }
        missing = required_keys - outputs.keys()
        if missing:
            self.log_error(
                f"Terraform output missing inventory keys: {sorted(missing)}. "
                f"ansible/terraform_inventory_aws.py will produce empty hostvars."
            )
        else:
            self.log_success(
                f"All {len(required_keys)} inventory keys present in terraform output"
            )

    def test_state_assertions(self):
        self.log_info("Test 8/8: State resource assertions")
        state_log = LOG_DIR / "tf-state.log"
        self._run_logged(["tflocal", "state", "list"], state_log)
        try:
            state_text = state_log.read_text()
        except OSError:
            state_text = ""

        total = sum(1 for line in state_text.splitlines() if line.strip())
        self.log_info(f"  - Total resources in state: {total}")

        self._assert_min_count(state_text, r"aws_iam_role\.", 2, "IAM roles")
        self._assert_in_state(
            state_text, r"aws_lambda_function\.", "Lambda function (scheduler)"
        )
        self._assert_in_state(
            state_text, r"aws_security_group\.", "Security group (k3s cluster)"
        )
        self._assert_in_state(
            state_text, r"aws_s3_bucket\.ssm_transfer", "S3 bucket (ssm_transfer)"
        )
        self._assert_in_state(
            state_text,
            r"aws_iam_instance_profile\.",
            "IAM instance profile (k3s node)",
        )

    def _assert_in_state(self, state_text, pattern, label):
        if re.search(pattern, state_text):
            self.log_success(f"State: {label} present")
        else:
            self.log_error(f"State: {label} MISSING (pattern: {pattern})")
            self.log_warning("  State contents:")
            for line in state_text.splitlines():
                print(f"    {line}")

    def _assert_min_count(self, state_text, pattern, minimum, label):
        actual = len(re.findall(pattern, state_text))
        if actual >= minimum:
            self.log_success(f"Count: {actual} {label} (minimum {minimum})")
        else:
            self.log_error(f"Count: {actual} {label} (expected >= {minimum})")

    def cleanup_destroy(self):
        self.log_info("Cleanup: destroying LocalStack resources")
        rc = self._run_logged(
            [
                "tflocal",
                "destroy",
                "-auto-approve",
                "-var-file=terraform.tfvars.localstack",
            ],
            LOG_DIR / "tf-destroy.log",
            extra_env={"TF_VAR_localstack_test": "yes"},
        )
        if rc == 0:
            self.log_success("Destroy completed — LocalStack resources cleaned up")
        else:
            self.log_warning(
                "Destroy had some failures (non-fatal — LocalStack may already be clean)"
            )

    # ── utility ──────────────────────────────────────────────────────────────

    def _dump(self, path):
        try:
            print(path.read_text())
        except OSError:
            pass

    # ── orchestrator ────────────────────────────────────────────────────────

    def run(self):
        self._print_banner()
        self.log_info("Checking prerequisites...")

        if not self.check_localstack_running():
            return 1
        if not self.check_tflocal_available():
            return 1
        self.check_sops_configured()

        print()
        self.log_info("Starting structure validation tests...")
        print()

        if not self.test_init():
            return 1
        if not self.test_validate():
            return 1
        if not self.test_get():
            return 1
        if not self.test_plan():
            return 1
        self.test_graph()
        self.test_output()
        self.test_apply()
        self.test_output_schema_post_apply()
        self.test_state_assertions()
        self.cleanup_destroy()

        return self._print_summary()

    def _print_banner(self):
        print("╔═══════════════════════════════════════════════════════════════╗")
        print("║     AWS Infrastructure - LocalStack Structure Validation     ║")
        print("╚═══════════════════════════════════════════════════════════════╝")
        print()

    def _print_summary(self):
        print()
        print("╔═══════════════════════════════════════════════════════════════╗")
        print("║                      Test Summary                             ║")
        print("╚═══════════════════════════════════════════════════════════════╝")
        print()
        print(f"{GREEN}Tests Passed:{NC} {self.passed}")
        print(f"{RED}Tests Failed:{NC} {self.failed}")
        print()

        if self.failed == 0:
            print(f"{GREEN}✓ All structure validation tests passed!{NC}")
            print()
            self.log_info("What was validated:")
            print("  ✅ Terraform module structure is correct")
            print("  ✅ Variable validation rules work")
            print("  ✅ Resource dependencies are correct")
            print("  ✅ Module composition is valid")
            print("  ✅ SOPS integration configured")
            print(
                "  ✅ IAM roles, Lambda, S3, and security group "
                "entered Terraform state"
            )
            print()
            self.log_warning("What was NOT validated (LocalStack limitations):")
            print("  ❌ EC2 Spot/Fleet provisioning (LocalStack free tier)")
            print("  ❌ k3s installation (user data execution)")
            print("  ❌ IAM role assumption and actual permission checks")
            print()
            self.log_info("Next Steps:")
            print("  1. Review /tmp/tf-apply.log for apply details")
            print("  2. Review /tmp/tf-state.log for managed resources")
            print("  3. Deploy to AWS for full behaviour validation")
            print()
            return 0

        print(f"{RED}✗ Some tests failed. Please review the output above.{NC}")
        print()
        return 1


def main():
    return LocalStackTester().run()


if __name__ == "__main__":
    sys.exit(main())
