"""Shared pytest configuration for bin/tests/.

Provides the `--run-live` opt-in flag for tests marked with
`@pytest.mark.live`. Live tests need a real cluster / external service
and are skipped by default so the unit-test suite stays hermetic.

Usage:
  python3 -m pytest bin/tests/                     # unit tests only
  python3 -m pytest bin/tests/ --run-live          # include live tests
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.live (requires live cluster / services)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="needs --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
