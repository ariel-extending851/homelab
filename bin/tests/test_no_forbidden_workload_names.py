"""Compliance contract: no forbidden workload product names in Alloy artifacts.

The Alloy observability pipeline ships under a strict labeling taxonomy:
workloads are referred to ONLY as "Containerized Microservice", "Media
Streaming Daemon", or "High-Throughput Local Service". Individual product
names must not appear in any of the Alloy configuration, role templates,
documentation, or related files.

This test enforces that at the repository level. The runtime defensive
guard in config.alloy (the `cardinality_guard` relabel block + the
`loki.process.normalize` drop rule) is belt-and-braces — this test is the
braces.

Add new forbidden names to FORBIDDEN_NAMES below. Add new paths to scan
under SCAN_PATHS if Alloy expands into additional repo locations.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

FORBIDDEN_NAMES: tuple[str, ...] = (
    "jellyfin",
    "radarr",
    "sonarr",
    "jackett",
    "prowlarr",
    "lidarr",
    "readarr",
    "bazarr",
)

# Word-boundary-anchored, case-insensitive. The wildcard "*arr" lives in the
# runtime regex (config.alloy) but is too broad here — it would false-positive
# on benign English words ("starr", "warrant", etc).
FORBIDDEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in FORBIDDEN_NAMES) + r")\b",
    re.IGNORECASE,
)

# The forbidden names ARE allowed inside the explicit drop-regex declarations.
# Each allowed mention is justified by its surrounding context: it documents
# what's being filtered, not a real workload reference.
# Patterns matched:
#   - Words documenting compliance / drop intent (forbidden, drop, defensive)
#   - River drop-rule syntax:  regex = "..."  or  expression = "..."
#   - Jinja variable holding the regex:  alloy_forbidden_label_regex
#   - Pytest / Ansible test assertions:   regex_search(...)
#   - Documentation cross-references to this file or the runbook
ALLOWED_REGEX_CONTEXT_RE = re.compile(
    r"(forbidden|drop|FORBIDDEN_NAMES|alloy_forbidden_label_regex|defensive|compliance|"
    r"^\s*regex\s*=|^\s*expression\s*=|regex_search\s*\(|"
    r"docs/architecture/observability-alloy-ebpf|docs/runbooks/alloy-troubleshooting|"
    r"# Add new forbidden names|alloy_native|never appear|never mention)",
    re.IGNORECASE | re.MULTILINE,
)

# Files scanned by this test. Both Alloy-specific paths (where the rule is
# absolute) and Alloy-touching docs (where the names are allowed only inside
# the explicit drop-regex declarations).
SCAN_PATHS: tuple[pathlib.Path, ...] = (
    REPO_ROOT / "k8s" / "apps" / "alloy",
    REPO_ROOT / "ansible" / "roles" / "alloy",
    REPO_ROOT / "docs" / "architecture" / "observability-alloy-ebpf.md",
    REPO_ROOT / "docs" / "runbooks" / "alloy-troubleshooting.md",
    REPO_ROOT / "docs" / "architecture" / "portfolio-observability-pipeline-README.md",
)

# Files to never scan even if they live under a scan path: lockfiles, binary
# artifacts, this test itself (it must mention the names verbatim).
SKIP_FILES: frozenset[str] = frozenset(
    {
        "test_no_forbidden_workload_names.py",
    }
)


def _iter_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in SCAN_PATHS:
        if not root.exists():
            continue
        if root.is_file():
            files.append(root)
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in SKIP_FILES:
                continue
            if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip"}:
                continue
            files.append(path)
    return files


@pytest.mark.parametrize(
    "path", _iter_files(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_forbidden_workload_name(path: pathlib.Path) -> None:
    """Each scanned file must contain no forbidden product names outside the
    explicit drop-regex declarations."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        pytest.skip(f"{path} is not UTF-8 text")
        return

    violations: list[tuple[int, str]] = []
    for line_num, line in enumerate(text.splitlines(), start=1):
        if FORBIDDEN_RE.search(line) and not ALLOWED_REGEX_CONTEXT_RE.search(line):
            violations.append((line_num, line.strip()))

    if violations:
        # Render every offending line so the operator can fix in one pass.
        rendered = "\n".join(f"  {path}:{ln}: {line}" for ln, line in violations)
        pytest.fail(
            f"Forbidden workload product name(s) found in {path.relative_to(REPO_ROOT)}:\n"
            f"{rendered}\n\n"
            f"Refer to these workloads as 'Containerized Microservices', "
            f"'Media Streaming Daemons', or 'High-Throughput Local Services'. "
            f"See docs/architecture/observability-alloy-ebpf.md."
        )


def test_scan_produces_at_least_one_file() -> None:
    """Guard against the test silently passing because the scan path lookup
    broke — at minimum the configmap.yaml must be scanned."""
    files = _iter_files()
    assert files, "No files scanned — SCAN_PATHS appears broken"
    expected = REPO_ROOT / "k8s" / "apps" / "alloy" / "configmap.yaml"
    assert expected in files, (
        f"Expected to scan {expected} but it was missing from the file list. "
        f"Got: {[str(f.relative_to(REPO_ROOT)) for f in files]}"
    )
