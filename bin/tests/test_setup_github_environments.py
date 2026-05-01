"""Tests for bin/setup_github_environments.py.

Mocks subprocess + injected user-ID resolver so the suite never calls `gh`.
Asserts the env body shapes (wait_timer, reviewers, branch policy) and the
ordering of PUT calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import setup_github_environments as g  # noqa: E402


# ── pure helpers ────────────────────────────────────────────────────────────


def test_reviewer_payload_resolves_each_username():
    ids = {"alice": 1001, "bob": 1002}
    payload = g.reviewer_payload("alice,bob", id_resolver=ids.__getitem__)
    assert payload == [
        {"type": "User", "id": 1001},
        {"type": "User", "id": 1002},
    ]


def test_reviewer_payload_strips_whitespace_and_skips_empty():
    payload = g.reviewer_payload(" alice , , bob ", id_resolver=lambda u: 42)
    assert [r["id"] for r in payload] == [42, 42]
    assert all(r["type"] == "User" for r in payload)


def test_reviewer_payload_empty_string_returns_empty_list():
    assert g.reviewer_payload("", id_resolver=lambda u: 0) == []


def test_env_body_staging_has_no_reviewers_or_wait():
    body = g.env_body_staging()
    assert body["wait_timer"] == 0
    assert body["reviewers"] == []
    assert body["deployment_branch_policy"] is None


def test_env_body_production_approval_carries_5min_wait_and_reviewers():
    reviewers = [{"type": "User", "id": 1}]
    body = g.env_body_production_approval(reviewers)
    assert body["wait_timer"] == 5
    assert body["reviewers"] == reviewers
    assert body["deployment_branch_policy"]["protected_branches"] is True


def test_env_body_production_restricts_to_protected_branches():
    body = g.env_body_production()
    assert body["wait_timer"] == 0
    assert body["reviewers"] == []
    assert body["deployment_branch_policy"]["protected_branches"] is True


# ── put_env ────────────────────────────────────────────────────────────────


def test_put_env_invokes_gh_api_with_correct_url_and_body():
    with patch.object(g, "gh_api") as gh_api:
        g.put_env("acme/repo", "production-approval", {"wait_timer": 5})
    args, kwargs = gh_api.call_args
    cli_args = args[0]
    assert "PUT" in cli_args
    assert "repos/acme/repo/environments/production-approval" in cli_args
    body = json.loads(kwargs["input_str"])
    assert body == {"wait_timer": 5}


# ── main: orchestration end-to-end with mocks ──────────────────────────────


def test_main_creates_three_environments_in_order(monkeypatch, capsys):
    monkeypatch.setattr(g, "repo_slug", lambda: "acme/repo")
    monkeypatch.setattr(g, "repo_owner", lambda: "alice")
    monkeypatch.setattr(g, "resolve_user_id", lambda u: 1001)

    put_calls = []

    def fake_put(slug, name, body):
        put_calls.append((slug, name, body))

    monkeypatch.setattr(g, "put_env", fake_put)
    monkeypatch.setattr(g, "gh_api", lambda *a, **k: '{"environments": []}')

    rc = g.main([])

    assert rc == 0
    names = [name for _, name, _ in put_calls]
    assert names == [g.ENV_STAGING, g.ENV_PROD_APPROVAL, g.ENV_PROD]

    # production-approval body has the resolved reviewer.
    prod_approval_body = next(b for _, n, b in put_calls if n == g.ENV_PROD_APPROVAL)
    assert prod_approval_body["reviewers"] == [{"type": "User", "id": 1001}]
    assert prod_approval_body["wait_timer"] == 5


def test_main_uses_explicit_reviewers_flag(monkeypatch):
    monkeypatch.setattr(g, "repo_slug", lambda: "acme/repo")
    monkeypatch.setattr(g, "repo_owner", lambda: "alice")  # would be ignored
    monkeypatch.setattr(g, "resolve_user_id", lambda u: {"bob": 1, "carol": 2}[u])

    put_calls = []
    monkeypatch.setattr(
        g, "put_env", lambda slug, name, body: put_calls.append((name, body))
    )
    monkeypatch.setattr(g, "gh_api", lambda *a, **k: '{"environments": []}')

    g.main(["--reviewers", "bob,carol"])

    prod_approval_body = next(b for n, b in put_calls if n == g.ENV_PROD_APPROVAL)
    assert prod_approval_body["reviewers"] == [
        {"type": "User", "id": 1},
        {"type": "User", "id": 2},
    ]
