#!/usr/bin/env python3
"""
Render k3s Jinja2 templates with representative test variables and validate
the resulting YAML for parse errors and required field presence.

Run from the repo root:
  python3 scripts/render_and_lint_templates.py

Variables mirror ansible/roles/k3s/molecule/default/molecule.yml group_vars
so the same fixture data drives both molecule tests and this static check.
"""
import sys
import yaml
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATES_DIR = Path("ansible/roles/k3s/templates")

SERVER_VARS = {
    "k3s_server_config": {
        "write_kubeconfig_mode": "0644",
        "cluster_cidr": "10.42.0.0/16",
        "service_cidr": "10.43.0.0/16",
        "tls_san": ["127.0.0.1", "k3s-server-node"],
        "disable": ["traefik"],
        "flannel_backend": "vxlan",
        "disable_cloud_controller": True,
        "disable_network_policy": False,
    },
    "k3s_enable_etcd_snapshots": False,
    "k3s_etcd_snapshot_schedule": "0 */12 * * *",
    "k3s_etcd_snapshot_retention": 5,
    "k3s_secrets_encryption": False,
    "k3s_protect_kernel_defaults": False,
    "k3s_node_name": "k3s-server-node",
}

AGENT_VARS = {
    "k3s_node_name": "k3s-agent-node",
    "k3s_tailscale_ip": "",
    "k3s_agent_config": {
        "node_label": [],
        "node_taint": [],
    },
    "k3s_protect_kernel_defaults": False,
}

CASES = [
    (
        "server-config.yaml.j2",
        SERVER_VARS,
        ["cluster-cidr", "service-cidr", "flannel-backend", "node-name"],
    ),
    (
        "agent-config.yaml.j2",
        AGENT_VARS,
        ["node-name"],
    ),
]


def render_template(name: str, variables: dict) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env.get_template(name).render(**variables)


def main() -> None:
    errors: list[str] = []

    for template_name, variables, required_keys in CASES:
        print(f"Validating {template_name}...")

        try:
            rendered = render_template(template_name, variables)
        except Exception as exc:
            errors.append(f"{template_name}: render error — {exc}")
            continue

        try:
            data = yaml.safe_load(rendered)
        except yaml.YAMLError as exc:
            errors.append(f"{template_name}: YAML parse error — {exc}")
            continue

        if not isinstance(data, dict):
            errors.append(
                f"{template_name}: rendered to non-mapping type ({type(data).__name__})"
            )
            continue

        for key in required_keys:
            if key not in data:
                errors.append(f"{template_name}: missing required key '{key}'")

        if not any(e.startswith(template_name) for e in errors):
            print(f"  ✓ valid YAML, required keys present ({', '.join(required_keys)})")

    if errors:
        print("\nValidation errors:")
        for err in errors:
            print(f"  ✗ {err}")
        sys.exit(1)

    print("\n✓ All k3s templates validated successfully.")


if __name__ == "__main__":
    main()
