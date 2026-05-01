"""Tests for bin/check_molecule_idempotence.py."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_molecule_idempotence as cmi  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip())


def _make_scenario(
    roles_dir: Path, role: str, scenario: str, test_sequence: list[str] | None
) -> Path:
    path = roles_dir / role / "molecule" / scenario / "molecule.yml"
    if test_sequence is None:
        body = "driver:\n  name: docker\n"
    else:
        seq = "\n".join(f"    - {s}" for s in test_sequence)
        body = f"driver:\n  name: docker\nscenario:\n  test_sequence:\n{seq}\n"
    _write(path, body)
    return path


def test_default_sequence_counts_as_covered(tmp_path: Path) -> None:
    p = _make_scenario(tmp_path, "alpha", "default", test_sequence=None)
    report = cmi.analyze_scenario(p)
    assert report.tests_idempotence is True
    assert report.sequence_explicit is False


def test_explicit_sequence_with_idempotence(tmp_path: Path) -> None:
    p = _make_scenario(
        tmp_path, "alpha", "default", ["converge", "idempotence", "verify"]
    )
    report = cmi.analyze_scenario(p)
    assert report.tests_idempotence is True
    assert report.sequence_explicit is True


def test_explicit_sequence_without_idempotence(tmp_path: Path) -> None:
    p = _make_scenario(tmp_path, "alpha", "default", ["converge", "verify"])
    report = cmi.analyze_scenario(p)
    assert report.tests_idempotence is False
    assert report.sequence_explicit is True


def test_strict_fails_when_undocumented_skip(tmp_path: Path, capsys) -> None:
    _make_scenario(tmp_path, "alpha", "default", ["converge"])
    exceptions = tmp_path / "exc.yml"
    exceptions.write_text("exceptions: []\n")
    rc = cmi.main(
        [
            "--roles-dir",
            str(tmp_path),
            "--exceptions",
            str(exceptions),
            "--strict",
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "UNDOCUMENTED" in captured.out
    assert "skip idempotence" in captured.err


def test_strict_passes_when_skip_is_documented(tmp_path: Path) -> None:
    _make_scenario(tmp_path, "alpha", "default", ["converge"])
    exceptions = tmp_path / "exc.yml"
    exceptions.write_text(
        "exceptions:\n  - role: alpha\n    scenario: default\n"
        "    reason: pre-created stubs prevent idempotence\n"
    )
    rc = cmi.main(
        [
            "--roles-dir",
            str(tmp_path),
            "--exceptions",
            str(exceptions),
            "--strict",
        ]
    )
    assert rc == 0


def test_non_strict_passes_when_skip_undocumented(tmp_path: Path) -> None:
    _make_scenario(tmp_path, "alpha", "default", ["converge"])
    exceptions = tmp_path / "exc.yml"
    exceptions.write_text("exceptions: []\n")
    rc = cmi.main(
        [
            "--roles-dir",
            str(tmp_path),
            "--exceptions",
            str(exceptions),
        ]
    )
    assert rc == 0


def test_exceptions_require_reason(tmp_path: Path) -> None:
    exc = tmp_path / "exc.yml"
    exc.write_text("exceptions:\n  - role: alpha\n    scenario: default\n")
    with pytest.raises(ValueError, match="missing role/scenario/reason"):
        cmi.load_exceptions(exc)


def test_no_scenarios_returns_error(tmp_path: Path, capsys) -> None:
    exceptions = tmp_path / "exc.yml"
    exceptions.write_text("exceptions: []\n")
    rc = cmi.main(
        [
            "--roles-dir",
            str(tmp_path),
            "--exceptions",
            str(exceptions),
        ]
    )
    assert rc == 2
    assert "No molecule.yml" in capsys.readouterr().err


def test_real_repo_passes_strict_mode() -> None:
    """The real repo state must satisfy strict idempotence coverage."""
    repo_root = Path(__file__).resolve().parents[2]
    roles_dir = repo_root / "ansible" / "roles"
    exceptions = repo_root / "ansible" / ".molecule-idempotence-exceptions.yml"
    if not roles_dir.exists() or not exceptions.exists():
        pytest.skip("Real repo paths not available in this checkout")
    rc = cmi.main(
        [
            "--roles-dir",
            str(roles_dir),
            "--exceptions",
            str(exceptions),
            "--strict",
        ]
    )
    assert rc == 0
