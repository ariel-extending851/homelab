#!/usr/bin/env python3
"""Validate that every Molecule scenario tests playbook idempotence.

A scenario tests idempotence when:
  - It does not declare a custom `scenario.test_sequence`, OR
  - Its `test_sequence` includes the string `idempotence`.

Scenarios that legitimately must skip idempotence (e.g., container kernel
limitations) are listed in `ansible/.molecule-idempotence-exceptions.yml`
with a documented `reason`. In `--strict` mode any scenario that skips
idempotence without an exception entry causes a non-zero exit.

Usage:
    bin/check_molecule_idempotence.py --roles-dir ansible/roles \\
        --exceptions ansible/.molecule-idempotence-exceptions.yml --strict
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_TEST_SEQUENCE_INCLUDES_IDEMPOTENCE = True


@dataclass(frozen=True)
class ScenarioReport:
    role: str
    scenario: str
    path: Path
    tests_idempotence: bool
    sequence_explicit: bool


def discover_scenarios(roles_dir: Path) -> list[Path]:
    return sorted(roles_dir.glob("*/molecule/*/molecule.yml"))


def analyze_scenario(molecule_yml: Path) -> ScenarioReport:
    role = molecule_yml.parents[2].name
    scenario = molecule_yml.parent.name
    data = yaml.safe_load(molecule_yml.read_text()) or {}
    sequence = (data.get("scenario") or {}).get("test_sequence")
    if sequence is None:
        return ScenarioReport(
            role,
            scenario,
            molecule_yml,
            DEFAULT_TEST_SEQUENCE_INCLUDES_IDEMPOTENCE,
            False,
        )
    return ScenarioReport(role, scenario, molecule_yml, "idempotence" in sequence, True)


def load_exceptions(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    out: dict[tuple[str, str], str] = {}
    for entry in data.get("exceptions", []):
        role = entry.get("role")
        scenario = entry.get("scenario")
        reason = entry.get("reason", "")
        if not role or not scenario or not reason.strip():
            raise ValueError(f"Exception entry missing role/scenario/reason: {entry!r}")
        out[(role, scenario)] = reason
    return out


def render_report(
    reports: list[ScenarioReport], exceptions: dict[tuple[str, str], str]
) -> tuple[int, int, list[str]]:
    lines: list[str] = []
    covered = 0
    skipped_undocumented = 0
    for r in sorted(reports, key=lambda x: (x.role, x.scenario)):
        key = (r.role, r.scenario)
        if r.tests_idempotence:
            covered += 1
            kind = "default" if not r.sequence_explicit else "explicit"
            lines.append(f"  ✓ {r.role}/{r.scenario} (idempotence: {kind})")
        elif key in exceptions:
            lines.append(
                f"  ⚠ {r.role}/{r.scenario} skips idempotence "
                f"— documented: {exceptions[key]}"
            )
        else:
            skipped_undocumented += 1
            lines.append(f"  ✗ {r.role}/{r.scenario} skips idempotence — UNDOCUMENTED")
    return covered, skipped_undocumented, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roles-dir", required=True, type=Path)
    parser.add_argument("--exceptions", required=True, type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any scenario lacks documented idempotence coverage",
    )
    args = parser.parse_args(argv)

    scenarios = discover_scenarios(args.roles_dir)
    if not scenarios:
        print(f"❌ No molecule.yml files found under {args.roles_dir}", file=sys.stderr)
        return 2

    exceptions = load_exceptions(args.exceptions)
    reports = [analyze_scenario(p) for p in scenarios]
    covered, skipped, lines = render_report(reports, exceptions)

    print(f"Molecule idempotence coverage ({covered}/{len(reports)} scenarios):")
    print("\n".join(lines))

    if skipped and args.strict:
        print(
            f"\n❌ {skipped} scenario(s) skip idempotence without an entry in "
            f"{args.exceptions}.\n"
            f"   Either add the idempotence step to the scenario, or document "
            f"the exception with a reason.",
            file=sys.stderr,
        )
        return 1

    print(
        f"\n✅ Idempotence coverage validated "
        f"({covered} covered, {len(exceptions)} documented exceptions)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
