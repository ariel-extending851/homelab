#!/usr/bin/env python3
"""
Homelab version scanner and updater.

Scans Ansible requirements.yml, Terraform providers, and Kubernetes manifests
for outdated versions, creates a git branch with the updates, runs local
linting, and stages the changes for your review.

Usage:
  python3 bin/update_versions.py            # scan + update + branch + lint + stage
  python3 bin/update_versions.py --dry-run  # report only, no file changes
  make update-versions
  make update-versions-dry-run

Exit codes:
  0  all components up-to-date
  1  updates found and applied (or --dry-run found outdated components)
  2  fatal error (bad environment, etc.)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent

BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class VersionUpdate:
    name: str
    current: str
    latest: str
    outdated: bool
    files: list[Path] = field(default_factory=list)
    skip_reason: str = ""
    error: str = ""


# ── Ansible collection specs ──────────────────────────────────────────────────

ANSIBLE_COLLECTIONS: list[tuple[str, str]] = [
    ("kubernetes", "core"),
    ("community", "sops"),
    ("community", "general"),
    ("ansible", "posix"),
]


# ── Terraform provider specs ──────────────────────────────────────────────────
# (namespace, provider_name, list_of_tf_files_relative_to_repo_root)

TF_PROVIDERS: list[tuple[str, str, list[str]]] = [
    ("hashicorp", "aws", [
        "infra/aws/main.tf",
        "infra/aws-backend/main.tf",
        "infra/aws-oidc/versions.tf",
        "infra/aws/modules/compute/versions.tf",
        "infra/aws/modules/network/versions.tf",
        "infra/aws/modules/scheduler/versions.tf",
    ]),
    ("carlpett", "sops", ["infra/aws/main.tf"]),
    ("tailscale", "tailscale", ["infra/aws/main.tf"]),
    ("hashicorp", "random", ["infra/aws-backend/main.tf"]),
    ("hashicorp", "archive", ["infra/aws/modules/scheduler/versions.tf"]),
]


# ── Kubernetes image specs ────────────────────────────────────────────────────

@dataclass
class ImageSpec:
    image_ref: str          # full ref as it appears in YAML, e.g. "grafana/grafana:10.2.3"
    registry: str           # "dockerhub" | "quay" | "github_releases"
    lookup: str             # repo path used for API calls
    tag_pattern: str = r"^v?\d+\.\d+(\.\d+)*$"
    skip: bool = False
    skip_reason: str = ""


K8S_IMAGES: list[ImageSpec] = [
    # ── Observability stack ──────────────────────────────────────────────────
    ImageSpec("grafana/grafana:10.2.3",                   "dockerhub", "grafana/grafana"),
    ImageSpec("prom/prometheus:v2.45.0",                  "dockerhub", "prom/prometheus"),
    ImageSpec("grafana/loki:2.9.2",                       "dockerhub", "grafana/loki"),
    ImageSpec("quay.io/prometheus/blackbox-exporter:v0.24.0", "quay",  "prometheus/blackbox-exporter"),
    ImageSpec("quay.io/prometheus/node-exporter:v1.7.0",  "quay",      "prometheus/node-exporter"),
    ImageSpec("registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.9.2",
              "github_releases", "kubernetes/kube-state-metrics"),
    ImageSpec("otel/opentelemetry-collector-contrib:0.102.0", "dockerhub",
              "otel/opentelemetry-collector-contrib"),
    # ── Apps ─────────────────────────────────────────────────────────────────
    ImageSpec("adguard/adguardhome:v0.107.71",            "dockerhub", "adguard/adguardhome"),
    ImageSpec("***/***:10.10.3",                "dockerhub", "***/***"),
    ImageSpec("qmcgaw/***:v3.38.0",                   "dockerhub", "qmcgaw/***"),
    ImageSpec("ghcr.io/***/***:v3.4.2", "github_releases",
              "***/***"),
    # ── Media stack (linuxserver images) ─────────────────────────────────────
    ImageSpec("lscr.io/linuxserver/***:2.3.5.5327-ls142", "dockerhub",
              "linuxserver/***", tag_pattern=r"^\d+\.\d+\.\d+[\.\d]*-ls\d+$"),
    ImageSpec("lscr.io/linuxserver/***:5.0.3",    "dockerhub",
              "linuxserver/***", tag_pattern=r"^\d+\.\d+(\.\d+)*(-[a-z0-9]+-ls\d+)?$"),
    ImageSpec("lscr.io/linuxserver/***:5.19.3",        "dockerhub",
              "linuxserver/***",      tag_pattern=r"^\d+\.\d+(\.\d+)*(-[a-z0-9]+-ls\d+)?$"),
    ImageSpec("lscr.io/linuxserver/***:4.0.13",        "dockerhub",
              "linuxserver/***",      tag_pattern=r"^\d+\.\d+(\.\d+)*(-[a-z0-9]+-ls\d+)?$"),
    # ── Utility base images ───────────────────────────────────────────────────
    ImageSpec("busybox:1.36",                             "dockerhub", "library/busybox"),
    # ── Skipped: digest-pinned, rolling, or utility images ───────────────────
    ImageSpec(
        "ghcr.io/tailscale/golink:main@sha256:ba5303fefc041cf9f11f960a90c3e16ca922dad8140ef43f704670f5c55f581b",
        "github_releases", "tailscale/golink",
        skip=True, skip_reason="digest-pinned — update manually",
    ),
    ImageSpec(
        "searxng/searxng:2026.2.14-39ac4d438",
        "dockerhub", "searxng/searxng",
        skip=True, skip_reason="rolling date+commit tags — update manually",
    ),
    ImageSpec(
        "alpine:3.19", "dockerhub", "library/alpine",
        skip=True, skip_reason="utility init-container — pin manually",
    ),
    ImageSpec(
        "alpine/k8s:1.28.2", "dockerhub", "alpine/k8s",
        skip=True, skip_reason="utility cronjob image — pin manually",
    ),
    ImageSpec(
        "curlimages/curl:8.5.0", "dockerhub", "curlimages/curl",
        skip=True, skip_reason="utility job image — pin manually",
    ),
]


# ── HTTP helper ───────────────────────────────────────────────────────────────

def fetch_json(url: str, timeout: int = 15) -> dict | None:
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "homelab-update-scanner/1.0",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


# ── Version parsing and comparison ────────────────────────────────────────────

_UNSTABLE_TAG = re.compile(
    r"(^latest$|^edge$|^nightly$|^main$|^develop(ment)?$|^master$|"
    r"alpha|beta|rc\d|snapshot|arm64|amd64|linux-|windows-|\.sig$|\.att$)",
    re.IGNORECASE,
)


def _is_stable_tag(tag: str) -> bool:
    if not tag:
        return False
    if _UNSTABLE_TAG.search(tag):
        return False
    if re.fullmatch(r"[a-f0-9]{12,}", tag):  # bare commit SHA
        return False
    return True


def _version_key(tag: str) -> tuple[int, ...]:
    """Convert a tag to a comparable numeric tuple, stripping v-prefix and ls-suffix."""
    raw = tag.lstrip("v")
    # For linuxserver tags like "5.0.3-r0-ls279": extract ls build as tiebreaker
    ls_match = re.search(r"-ls(\d+)$", raw)
    ls_num = int(ls_match.group(1)) if ls_match else 0
    # Take the leading numeric portion (stops at first non-digit/dot)
    numeric_part = re.split(r"[^0-9.]", raw)[0].strip(".")
    parts: tuple[int, ...] = tuple(int(p) for p in numeric_part.split(".") if p.isdigit())
    return parts + (ls_num,)


def is_newer(latest: str, current: str) -> bool:
    """Return True if latest is strictly newer than current."""
    try:
        return _version_key(latest) > _version_key(current)
    except Exception:
        return False


def _best_tag(tags: list[str], pattern: str) -> str:
    """Return the highest stable tag that matches the given regex pattern."""
    stable = [t for t in tags if _is_stable_tag(t) and re.fullmatch(pattern, t)]
    if not stable:
        return ""
    return max(stable, key=_version_key)


# ── Terraform constraint helpers ──────────────────────────────────────────────

def constraint_needs_update(constraint: str, latest_version: str) -> tuple[bool, str]:
    """
    Given a Terraform ~> constraint and a latest provider version, return
    (needs_update, suggested_new_constraint).

    Examples:
      "~> 5.0"   + "6.36.0" → (True,  "~> 6.0")
      "~> 5.0"   + "5.82.0" → (False, "~> 5.0")
      "~> 0.7.0" + "0.9.1"  → (True,  "~> 0.9.0")
      "~> 0.13"  + "0.17.0" → (False, "~> 0.13")
    """
    m = re.match(r"~>\s*(\d+)\.(\d+)(?:\.(\d+))?", constraint)
    if not m:
        return False, constraint

    c_major, c_minor = int(m.group(1)), int(m.group(2))
    three_part = m.group(3) is not None

    latest_clean = latest_version.lstrip("v")
    parts = [int(p) for p in latest_clean.split(".")[:3]]
    l_major = parts[0]
    l_minor = parts[1] if len(parts) > 1 else 0

    if three_part:
        # ~> X.Y.Z  →  allows >= X.Y.Z, < X.(Y+1).0
        if l_major > c_major or (l_major == c_major and l_minor > c_minor):
            return True, f"~> {l_major}.{l_minor}.0"
        return False, constraint
    else:
        # ~> X.Y  →  allows >= X.Y, < (X+1).0
        if l_major > c_major:
            return True, f"~> {l_major}.0"
        return False, constraint


# ── Ansible Galaxy ────────────────────────────────────────────────────────────

def fetch_galaxy_version(namespace: str, name: str) -> str:
    url = (
        "https://galaxy.ansible.com/api/v3/plugin/ansible/content/published/"
        f"collections/index/{namespace}/{name}/"
    )
    data = fetch_json(url)
    if not data:
        raise RuntimeError(f"Galaxy API unreachable for {namespace}.{name}")
    hv = data.get("highest_version") or {}
    version = hv.get("version")
    if not version:
        raise RuntimeError(f"No version in Galaxy response for {namespace}.{name}")
    return version


def scan_ansible(repo_root: Path) -> list[VersionUpdate]:
    req_file = repo_root / "ansible" / "requirements.yml"
    with req_file.open() as fh:
        reqs = yaml.safe_load(fh)

    current_map = {c["name"]: c.get("version", "") for c in reqs.get("collections", [])}
    updates: list[VersionUpdate] = []

    for namespace, name in ANSIBLE_COLLECTIONS:
        fqcn = f"{namespace}.{name}"
        constraint = current_map.get(fqcn, "")
        try:
            latest = fetch_galaxy_version(namespace, name)
            current_ver = re.sub(r"[>=<~^]", "", constraint).strip() or "0.0.0"
            outdated = is_newer(latest, current_ver)
            updates.append(VersionUpdate(
                name=f"ansible/{fqcn}",
                current=constraint,
                latest=f">={latest}",
                outdated=outdated,
                files=[req_file],
            ))
        except Exception as exc:
            updates.append(VersionUpdate(
                name=f"ansible/{fqcn}", current=constraint, latest="",
                outdated=False, files=[req_file], error=str(exc),
            ))
    return updates


def update_ansible_requirements(updates: list[VersionUpdate], repo_root: Path) -> None:
    req_file = repo_root / "ansible" / "requirements.yml"
    content = req_file.read_text()
    for u in updates:
        if not u.outdated:
            continue
        _, fqcn = u.name.split("/", 1)
        # Replace: name: community.sops\n    version: ">=1.6.0"
        content = re.sub(
            rf'(name:\s+{re.escape(fqcn)}[^\n]*\n\s+version:\s+")[^"]*(")',
            rf"\g<1>{u.latest}\g<2>",
            content,
        )
    req_file.write_text(content)


# ── Terraform Registry ────────────────────────────────────────────────────────

def fetch_tf_provider_version(namespace: str, provider: str) -> str:
    url = f"https://registry.terraform.io/v1/providers/{namespace}/{provider}"
    data = fetch_json(url)
    if not data:
        raise RuntimeError(f"Terraform Registry unreachable for {namespace}/{provider}")
    version = data.get("version")
    if not version:
        raise RuntimeError(f"No version in Terraform Registry response for {namespace}/{provider}")
    return version


def _extract_tf_constraint(provider: str, hcl: str) -> str:
    """Pull the version constraint for a provider out of HCL text."""
    # source = "namespace/provider"\n      version = "~> X.Y"
    m = re.search(
        rf'source\s*=\s*"[^"]*/{re.escape(provider)}"\s*\n\s*version\s*=\s*"([^"]+)"',
        hcl,
    )
    if m:
        return m.group(1)
    # Some blocks list version before source
    m2 = re.search(
        rf'version\s*=\s*"([^"]+)"\s*\n\s*source\s*=\s*"[^"]*/{re.escape(provider)}"',
        hcl,
    )
    return m2.group(1) if m2 else ""


def scan_terraform(repo_root: Path) -> list[VersionUpdate]:
    updates: list[VersionUpdate] = []
    seen: set[str] = set()

    for namespace, provider, rel_files in TF_PROVIDERS:
        key = f"{namespace}/{provider}"
        if key in seen:
            continue
        seen.add(key)

        files = [repo_root / f for f in rel_files if (repo_root / f).exists()]
        constraint = ""
        for f in files:
            c = _extract_tf_constraint(provider, f.read_text())
            if c:
                constraint = c
                break

        try:
            latest = fetch_tf_provider_version(namespace, provider)
            needs_update, new_constraint = constraint_needs_update(constraint, latest)
            updates.append(VersionUpdate(
                name=f"terraform/{key}",
                current=constraint or "(not found)",
                latest=new_constraint if needs_update else f"{latest} (within {constraint})",
                outdated=needs_update,
                files=files,
            ))
        except Exception as exc:
            updates.append(VersionUpdate(
                name=f"terraform/{key}", current=constraint, latest="",
                outdated=False, files=files, error=str(exc),
            ))
    return updates


def update_terraform_files(updates: list[VersionUpdate], repo_root: Path) -> None:
    for u in updates:
        if not u.outdated:
            continue
        provider = u.name.split("/")[-1]
        for tf_file in u.files:
            content = tf_file.read_text()
            new_content = re.sub(
                rf'(source\s*=\s*"[^"]*/{re.escape(provider)}"\s*\n\s*version\s*=\s*")[^"]+(")',
                rf"\g<1>{u.latest}\g<2>",
                content,
            )
            if new_content != content:
                tf_file.write_text(new_content)


# ── Container registries ──────────────────────────────────────────────────────

def fetch_dockerhub_latest(repo: str, tag_pattern: str) -> str:
    tags: list[str] = []
    url: str | None = (
        f"https://hub.docker.com/v2/repositories/{repo}/tags/"
        "?page_size=100&ordering=last_updated"
    )
    while url and len(tags) < 300:
        data = fetch_json(url)
        if not data:
            break
        tags.extend(r["name"] for r in data.get("results", []))
        url = data.get("next")

    best = _best_tag(tags, tag_pattern)
    if not best:
        raise RuntimeError(f"No stable matching tag found on Docker Hub for {repo}")
    return best


def fetch_quay_latest(repo: str, tag_pattern: str) -> str:
    url = f"https://quay.io/api/v1/repository/{repo}/tag/?onlyActiveTags=true&limit=100"
    data = fetch_json(url)
    if not data:
        raise RuntimeError(f"Quay.io API unreachable for {repo}")
    tags = [t["name"] for t in data.get("tags", [])]
    best = _best_tag(tags, tag_pattern)
    if not best:
        raise RuntimeError(f"No stable matching tag found on Quay for {repo}")
    return best


def fetch_github_release_latest(owner_repo: str) -> str:
    url = f"https://api.github.com/repos/{owner_repo}/releases/latest"
    data = fetch_json(url)
    if not data or "tag_name" not in data:
        raise RuntimeError(f"GitHub releases API unreachable for {owner_repo}")
    return data["tag_name"]


def _latest_tag_for(spec: ImageSpec) -> str:
    if spec.registry == "dockerhub":
        return fetch_dockerhub_latest(spec.lookup, spec.tag_pattern)
    if spec.registry == "quay":
        return fetch_quay_latest(spec.lookup, spec.tag_pattern)
    if spec.registry == "github_releases":
        return fetch_github_release_latest(spec.lookup)
    raise RuntimeError(f"Unknown registry: {spec.registry}")


def _image_name(image_ref: str) -> str:
    """Strip the tag from an image ref: 'grafana/grafana:10.2.3' → 'grafana/grafana'."""
    return image_ref.split(":")[0] if ":" in image_ref else image_ref


def _current_tag(image_ref: str) -> str:
    """Extract the tag from an image ref: 'grafana/grafana:10.2.3' → '10.2.3'."""
    return image_ref.split(":")[-1] if ":" in image_ref else ""


def scan_k8s(repo_root: Path) -> list[VersionUpdate]:
    # Build map: full image ref → list of YAML files that contain it
    k8s_dir = repo_root / "k8s"
    ref_to_files: dict[str, list[Path]] = {}
    for yaml_file in k8s_dir.rglob("*.yaml"):
        try:
            for line in yaml_file.read_text().splitlines():
                m = re.match(r"\s+image:\s+(\S+)", line)
                if m:
                    ref = m.group(1)
                    ref_to_files.setdefault(ref, []).append(yaml_file)
        except Exception:
            pass

    updates: list[VersionUpdate] = []
    for spec in K8S_IMAGES:
        name = f"k8s/{_image_name(spec.image_ref)}"
        cur = _current_tag(spec.image_ref)

        if spec.skip:
            updates.append(VersionUpdate(
                name=name, current=cur, latest="", outdated=False,
                skip_reason=spec.skip_reason,
            ))
            continue

        files = ref_to_files.get(spec.image_ref, [])
        try:
            latest = _latest_tag_for(spec)
            outdated = is_newer(latest, cur)
            updates.append(VersionUpdate(
                name=name, current=cur, latest=latest,
                outdated=outdated, files=files,
            ))
        except Exception as exc:
            updates.append(VersionUpdate(
                name=name, current=cur, latest="",
                outdated=False, files=files, error=str(exc),
            ))
    return updates


def update_k8s_manifests(updates: list[VersionUpdate], repo_root: Path) -> None:
    # Build lookup: image name (no tag) → (spec, update)
    spec_by_name: dict[str, ImageSpec] = {_image_name(s.image_ref): s for s in K8S_IMAGES}

    for u in updates:
        if not u.outdated:
            continue
        image_name = u.name[len("k8s/"):]  # strip "k8s/" prefix
        spec = spec_by_name.get(image_name)
        if not spec:
            continue
        for f in u.files:
            old_line = f"image: {spec.image_ref}"
            new_line = f"image: {image_name}:{u.latest}"
            content = f.read_text()
            if old_line in content:
                f.write_text(content.replace(old_line, new_line))


# ── Git helpers ───────────────────────────────────────────────────────────────

def _git(args: list[str], repo_root: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo_root,
        capture_output=True, text=True, check=check,
    )


def git_create_branch(branch_name: str, repo_root: Path) -> bool:
    # Switch if branch already exists (idempotent re-runs on the same day)
    exists = _git(["show-ref", "--quiet", f"refs/heads/{branch_name}"], repo_root, check=False)
    if exists.returncode == 0:
        result = _git(["checkout", branch_name], repo_root, check=False)
    else:
        result = _git(["checkout", "-b", branch_name], repo_root, check=False)
    if result.returncode != 0:
        print(f"  {RED}git branch failed:{RESET} {result.stderr.strip()}")
        return False
    return True


def git_stage_files(paths: list[Path], repo_root: Path) -> None:
    for p in set(paths):
        _git(["add", str(p)], repo_root, check=False)


# ── Linting ───────────────────────────────────────────────────────────────────

def run_lint(repo_root: Path) -> list[str]:
    results: list[str] = []

    # 1. kustomize build — validates all Kubernetes manifests render correctly
    if shutil.which("kustomize"):
        r = subprocess.run(
            ["kustomize", "build", "k8s/apps"],
            cwd=repo_root, capture_output=True, text=True,
        )
        if r.returncode == 0:
            results.append(f"{GREEN}PASS{RESET} kustomize build k8s/apps")
        else:
            results.append(
                f"{RED}FAIL{RESET} kustomize build k8s/apps\n"
                f"       {r.stderr.strip()[:300]}"
            )
    else:
        results.append(
            f"{YELLOW}SKIP{RESET} kustomize not in PATH "
            "(run: mise exec -- kustomize build k8s/apps)"
        )

    # 2. terraform fmt -check — catches formatting drift in updated HCL files
    tf_dirs = [
        "infra/aws",
        "infra/aws-backend",
        "infra/aws-oidc",
        "infra/aws/modules/compute",
        "infra/aws/modules/network",
        "infra/aws/modules/scheduler",
    ]
    if shutil.which("terraform"):
        for tf_dir in tf_dirs:
            d = repo_root / tf_dir
            if not d.exists():
                continue
            r = subprocess.run(
                ["terraform", "fmt", "-check", "-diff"],
                cwd=d, capture_output=True, text=True,
            )
            label = tf_dir
            if r.returncode == 0:
                results.append(f"{GREEN}PASS{RESET} terraform fmt -check {label}")
            else:
                results.append(
                    f"{YELLOW}WARN{RESET} terraform fmt {label} "
                    f"(fix: cd {label} && terraform fmt)"
                )
    else:
        results.append(
            f"{YELLOW}SKIP{RESET} terraform not in PATH "
            "(run: mise exec -- terraform fmt -check infra/aws)"
        )

    # 3. yamllint — validates ansible/requirements.yml is still valid YAML
    if shutil.which("yamllint"):
        r = subprocess.run(
            ["yamllint", "ansible/requirements.yml"],
            cwd=repo_root, capture_output=True, text=True,
        )
        if r.returncode == 0:
            results.append(f"{GREEN}PASS{RESET} yamllint ansible/requirements.yml")
        else:
            results.append(
                f"{RED}FAIL{RESET} yamllint ansible/requirements.yml\n"
                f"       {r.stdout.strip()[:200]}"
            )
    else:
        results.append(f"{YELLOW}SKIP{RESET} yamllint not in PATH")

    return results


# ── Report ────────────────────────────────────────────────────────────────────

def _print_section(title: str, updates: list[VersionUpdate]) -> None:
    print(f"\n{BOLD}{title}{RESET}")
    for u in updates:
        if u.error:
            print(f"  {YELLOW}ERR {RESET} {u.name}: {u.error}")
        elif u.skip_reason:
            print(f"  {DIM}SKIP{RESET} {DIM}{u.name} — {u.skip_reason}{RESET}")
        elif u.outdated:
            print(f"  {RED}OUT {RESET} {u.name}: {u.current} → {BOLD}{u.latest}{RESET}")
        else:
            print(f"  {GREEN}OK  {RESET} {u.name}: {u.current}")


def print_report(
    ansible: list[VersionUpdate],
    terraform: list[VersionUpdate],
    k8s: list[VersionUpdate],
    lint: list[str],
    branch: str,
    dry_run: bool,
) -> int:
    _print_section("Ansible Collections", ansible)
    _print_section("Terraform Providers", terraform)
    _print_section("Kubernetes Images", k8s)

    if lint:
        print(f"\n{BOLD}Lint{RESET}")
        for line in lint:
            print(f"  {line}")

    all_updates = ansible + terraform + k8s
    outdated = [u for u in all_updates if u.outdated]
    errors = [u for u in all_updates if u.error]

    print()
    if outdated:
        print(f"{BOLD}Summary:{RESET} {RED}{len(outdated)} outdated component(s){RESET}")
        for u in outdated:
            print(f"  • {u.name}: {u.current} → {u.latest}")
    else:
        print(f"{BOLD}Summary:{RESET} {GREEN}All tracked components are up-to-date.{RESET}")

    if errors:
        print(
            f"\n{YELLOW}Note:{RESET} {len(errors)} component(s) could not be checked "
            "(network/API issue):"
        )
        for u in errors:
            print(f"  • {u.name}: {u.error}")

    if not dry_run and outdated:
        print(f"\n{GREEN}Branch:{RESET}  {branch}")
        print(f"{GREEN}Staged:{RESET}  {len(outdated)} file set(s) — review with:")
        print(f"  git diff --cached")
        print(f"  git commit -m 'chore: bump outdated versions ({date.today()})'")
    elif dry_run and outdated:
        print(f"\n{DIM}(dry-run — no files modified){RESET}")

    return 1 if outdated else 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report outdated versions without modifying any files.",
    )
    parser.add_argument(
        "--skip-lint", action="store_true",
        help="Skip post-update linting.",
    )
    parser.add_argument(
        "--skip-git", action="store_true",
        help="Skip branch creation and git staging.",
    )
    parser.add_argument(
        "--component", choices=["ansible", "terraform", "k8s"],
        help="Limit scan to a single component (default: all).",
    )
    args = parser.parse_args()

    today = date.today().isoformat()
    branch = f"chore/version-updates-{today}"

    print(f"{BOLD}Homelab Version Scanner{RESET} — {today}")
    print("Querying upstream registries…\n")

    ansible_updates: list[VersionUpdate] = []
    tf_updates: list[VersionUpdate] = []
    k8s_updates: list[VersionUpdate] = []

    if args.component in (None, "ansible"):
        print(f"  {DIM}→ Ansible Galaxy…{RESET}")
        ansible_updates = scan_ansible(REPO_ROOT)

    if args.component in (None, "terraform"):
        print(f"  {DIM}→ Terraform Registry…{RESET}")
        tf_updates = scan_terraform(REPO_ROOT)

    if args.component in (None, "k8s"):
        print(f"  {DIM}→ Container registries…{RESET}")
        k8s_updates = scan_k8s(REPO_ROOT)

    outdated = [u for u in ansible_updates + tf_updates + k8s_updates if u.outdated]
    lint_results: list[str] = []

    if not args.dry_run and outdated:
        if not args.skip_git:
            print(f"\nCreating branch {BOLD}{branch}{RESET}…")
            if not git_create_branch(branch, REPO_ROOT):
                print(f"{RED}Aborting: branch creation failed.{RESET}")
                return 2

        print("Applying updates…")
        if ansible_updates:
            update_ansible_requirements(
                [u for u in ansible_updates if u.outdated], REPO_ROOT
            )
        if tf_updates:
            update_terraform_files(
                [u for u in tf_updates if u.outdated], REPO_ROOT
            )
        if k8s_updates:
            update_k8s_manifests(
                [u for u in k8s_updates if u.outdated], REPO_ROOT
            )

        if not args.skip_lint:
            print("Running lint checks…")
            lint_results = run_lint(REPO_ROOT)

        if not args.skip_git:
            changed: list[Path] = []
            for u in outdated:
                changed.extend(u.files)
            print("Staging changes…")
            git_stage_files(changed, REPO_ROOT)

    return print_report(
        ansible_updates, tf_updates, k8s_updates,
        lint_results, branch, args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
