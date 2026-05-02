"""Tests for bin/rollback.py — ArgoCD revert + Terraform tag restore.

Rollback is destructive, so the unit tests focus on:
  - Pure parsing (history JSON → previous-good revision)
  - Decision logic (which revision to revert to)
  - Patch rendering (the kubectl --patch payload — no kubectl call)
  - Confirmation gate (refuses without --ack=I_AM_REVERTING)
  - Dry-run mode (default; mutating commands not executed)

Live execution paths (kubectl/git/terraform) are exercised via mocks.
"""

from __future__ import annotations

import json

import pytest

from bin import rollback as rb


# ── pure helpers ────────────────────────────────────────────────────────


def test_previous_good_revision_returns_second_synced():
    """ArgoCD .status.history is ordered oldest→newest. The current sync
    is the last entry; the previous-good is the second-to-last whose
    deployedAt is set (i.e. it actually completed)."""
    history = [
        {"revision": "aaa111", "deployedAt": "2026-04-01T00:00:00Z"},
        {"revision": "bbb222", "deployedAt": "2026-04-15T00:00:00Z"},
        {"revision": "ccc333", "deployedAt": "2026-05-01T00:00:00Z"},
    ]
    assert rb.previous_good_revision(history) == "bbb222"


def test_previous_good_revision_skips_undeployed_entries():
    """An entry without deployedAt represents a sync attempt that didn't
    complete — never a valid rollback target."""
    history = [
        {"revision": "aaa111", "deployedAt": "2026-04-01T00:00:00Z"},
        {"revision": "bbb222"},  # no deployedAt
        {"revision": "ccc333", "deployedAt": "2026-05-01T00:00:00Z"},
    ]
    assert rb.previous_good_revision(history) == "aaa111"


def test_previous_good_revision_empty_or_single_returns_none():
    assert rb.previous_good_revision([]) is None
    assert rb.previous_good_revision([{"revision": "abc", "deployedAt": "x"}]) is None


def test_render_argocd_targetrevision_patch():
    patch = rb.render_argocd_patch(target_revision="abc1234")
    obj = json.loads(patch)
    assert obj == {"spec": {"source": {"targetRevision": "abc1234"}}}


def test_parse_argocd_app_extracts_history_and_current_rev():
    raw = json.dumps(
        {
            "metadata": {"name": "homelab-apps-root", "namespace": "argocd"},
            "spec": {"source": {"targetRevision": "develop"}},
            "status": {
                "history": [
                    {"revision": "old1", "deployedAt": "2026-04-01T00:00:00Z"},
                    {"revision": "old2", "deployedAt": "2026-04-15T00:00:00Z"},
                ],
                "sync": {"revision": "current123"},
            },
        }
    )
    parsed = rb.parse_argocd_app(raw)
    assert parsed["name"] == "homelab-apps-root"
    assert parsed["current_revision"] == "current123"
    assert parsed["target_revision"] == "develop"
    assert len(parsed["history"]) == 2


def test_parse_argocd_app_handles_missing_status():
    raw = json.dumps({"metadata": {"name": "x"}, "spec": {}})
    parsed = rb.parse_argocd_app(raw)
    assert parsed["name"] == "x"
    assert parsed["history"] == []
    assert parsed["current_revision"] == ""


def test_parse_argocd_app_returns_empty_on_garbage():
    assert rb.parse_argocd_app("not-json") == {}
    assert rb.parse_argocd_app("") == {}


# ── confirmation gate ───────────────────────────────────────────────────


def test_assert_acked_raises_without_env(monkeypatch):
    monkeypatch.delenv("ROLLBACK_ACK", raising=False)
    with pytest.raises(rb.RollbackAborted):
        rb.assert_acked(ack_value=None)


def test_assert_acked_raises_on_wrong_value(monkeypatch):
    monkeypatch.delenv("ROLLBACK_ACK", raising=False)
    with pytest.raises(rb.RollbackAborted):
        rb.assert_acked(ack_value="yes")


def test_assert_acked_passes_with_correct_value():
    rb.assert_acked(ack_value=rb.ACK_SENTINEL)  # no raise


def test_assert_acked_reads_env_var(monkeypatch):
    monkeypatch.setenv("ROLLBACK_ACK", rb.ACK_SENTINEL)
    rb.assert_acked(ack_value=None)


# ── dry-run vs apply ────────────────────────────────────────────────────


def test_dry_run_argocd_no_kubectl_patch_called(monkeypatch, capsys):
    """Dry-run prints the intended patch but never invokes kubectl patch."""
    calls = []

    def fake_kubectl(*args, **kw):
        calls.append(args)
        # Pretend `kubectl get` succeeds with a minimal app.
        if "get" in args:
            return rb._FakeProc(
                returncode=0,
                stdout=json.dumps(
                    {
                        "metadata": {
                            "name": "homelab-apps-root",
                            "namespace": "argocd",
                        },
                        "spec": {"source": {"targetRevision": "develop"}},
                        "status": {
                            "history": [
                                {
                                    "revision": "old1",
                                    "deployedAt": "2026-04-01T00:00:00Z",
                                },
                                {
                                    "revision": "old2",
                                    "deployedAt": "2026-04-15T00:00:00Z",
                                },
                            ],
                            "sync": {"revision": "current"},
                        },
                    }
                ),
            )
        return rb._FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(rb, "_kubectl", fake_kubectl)
    rc = rb.rollback_argocd(
        app="homelab-apps-root",
        ack=rb.ACK_SENTINEL,
        dry_run=True,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "old1" in out  # would revert to this
    assert "[DRY-RUN]" in out
    # kubectl patch must NOT have been called.
    assert not any("patch" in str(c) for c in calls)


def test_apply_argocd_calls_kubectl_patch(monkeypatch):
    calls = []

    def fake_kubectl(*args, **kw):
        calls.append(args)
        if "get" in args:
            return rb._FakeProc(
                returncode=0,
                stdout=json.dumps(
                    {
                        "metadata": {
                            "name": "homelab-apps-root",
                            "namespace": "argocd",
                        },
                        "spec": {"source": {"targetRevision": "develop"}},
                        "status": {
                            "history": [
                                {
                                    "revision": "old1",
                                    "deployedAt": "2026-04-01T00:00:00Z",
                                },
                                {
                                    "revision": "old2",
                                    "deployedAt": "2026-04-15T00:00:00Z",
                                },
                            ],
                            "sync": {"revision": "current"},
                        },
                    }
                ),
            )
        return rb._FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(rb, "_kubectl", fake_kubectl)
    rc = rb.rollback_argocd(
        app="homelab-apps-root",
        ack=rb.ACK_SENTINEL,
        dry_run=False,
    )
    assert rc == 0
    # Must have called kubectl patch with the rendered payload.
    patch_calls = [c for c in calls if "patch" in c]
    assert len(patch_calls) == 1
    joined = " ".join(patch_calls[0])
    assert "old1" in joined  # the previous good revision
    assert "homelab-apps-root" in joined


def test_rollback_argocd_aborts_when_no_history(monkeypatch, capsys):
    def fake_kubectl(*args, **kw):
        if "get" in args:
            return rb._FakeProc(
                returncode=0,
                stdout=json.dumps(
                    {
                        "metadata": {"name": "homelab-apps-root"},
                        "spec": {"source": {"targetRevision": "develop"}},
                        "status": {"history": [], "sync": {"revision": "current"}},
                    }
                ),
            )
        return rb._FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(rb, "_kubectl", fake_kubectl)
    rc = rb.rollback_argocd(
        app="homelab-apps-root",
        ack=rb.ACK_SENTINEL,
        dry_run=False,
    )
    assert rc == 2  # distinct from "succeeded" (0) and "denied" (1)
    err = capsys.readouterr().err
    assert "no previous good revision" in err.lower()


def test_rollback_argocd_aborts_without_ack(monkeypatch):
    monkeypatch.delenv("ROLLBACK_ACK", raising=False)
    rc = rb.rollback_argocd(app="x", ack=None, dry_run=False)
    assert rc == 1


# ── terraform rollback ──────────────────────────────────────────────────


def test_terraform_rollback_dry_run_prints_target_tag(monkeypatch, capsys):
    """Dry-run shows `git checkout` + `terraform apply` but doesn't run them."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return rb._FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(rb.subprocess, "run", fake_run)
    rc = rb.rollback_terraform(
        target_tag="v0.42.0",
        ack=rb.ACK_SENTINEL,
        dry_run=True,
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "v0.42.0" in out
    assert "[DRY-RUN]" in out
    # No actual git / terraform calls in dry-run.
    assert not any("checkout" in str(c) for c in calls)
    assert not any("apply" in str(c) for c in calls)


def test_terraform_rollback_aborts_without_ack():
    rc = rb.rollback_terraform(target_tag="v0.42.0", ack="wrong-value", dry_run=False)
    assert rc == 1


# ── status subcommand ───────────────────────────────────────────────────


def test_status_argocd_lists_apps_with_history(monkeypatch, capsys):
    """`rollback.py status` is read-only — surfaces what could be reverted."""

    def fake_kubectl(*args, **kw):
        if "get" in args and "applications.argoproj.io" in args:
            return rb._FakeProc(
                returncode=0,
                stdout=json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {"name": "homelab-apps-root"},
                                "spec": {"source": {"targetRevision": "develop"}},
                                "status": {
                                    "history": [
                                        {
                                            "revision": "old1",
                                            "deployedAt": "2026-04-01T00:00:00Z",
                                        },
                                        {
                                            "revision": "current",
                                            "deployedAt": "2026-05-01T00:00:00Z",
                                        },
                                    ],
                                    "sync": {"revision": "current"},
                                },
                            }
                        ]
                    }
                ),
            )
        return rb._FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(rb, "_kubectl", fake_kubectl)
    rc = rb.status_argocd()
    assert rc == 0
    out = capsys.readouterr().out
    assert "homelab-apps-root" in out
    assert "current" in out
    assert "old1" in out


# ── main() routing ─────────────────────────────────────────────────────


def test_main_status_subcommand(monkeypatch, capsys):
    def fake_kubectl(*args, **kw):
        return rb._FakeProc(returncode=0, stdout=json.dumps({"items": []}))

    monkeypatch.setattr(rb, "_kubectl", fake_kubectl)
    rc = rb.main(["status"])
    assert rc == 0


def test_main_rejects_unknown_subcommand():
    with pytest.raises(SystemExit):
        rb.main(["unknown-thing"])
