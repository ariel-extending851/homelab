"""Pre-deploy / post-deploy rollback CLI — ArgoCD revert + Terraform tag restore.

Two destructive operations gated behind explicit acknowledgement:

  1. argocd  — Patches an ArgoCD Application's `.spec.source.targetRevision`
               to the previous-good commit pulled from `.status.history`.
               ArgoCD's auto-sync (selfHeal=true) then converges the cluster
               back to that state. Default subject: the root app-of-apps.

  2. terraform — `git checkout <tag>` for the infra/aws tree, then
               `terraform apply`. This UNDOES any infrastructure-level
               change that was rolled forward — destroy + recreate of EC2
               instances is possible, so the operator must pass the tag
               explicitly. No "auto-pick previous tag" magic.

Safety contract:

  - Default mode is `--dry-run` (prints the intended commands, never runs
    a mutating call).
  - Mutating runs require either `--ack=I_AM_REVERTING` on the CLI, or
    the equivalent `ROLLBACK_ACK` env var. Without it, the script aborts
    with rc=1.
  - The `status` subcommand is read-only and ungated.

Exit codes:

  0  rollback completed (or dry-run finished cleanly)
  1  acknowledgement missing or refused
  2  preconditions not met (no previous-good revision, kubectl unavailable,
     etc.) — distinct so CI can route it differently from a denied ack.

Manual runbook entry: docs/runbooks/control-plane-recovery.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

ACK_SENTINEL = "I_AM_REVERTING"
DEFAULT_APP = "homelab-apps-root"
DEFAULT_NAMESPACE = "argocd"
TF_DIR = "infra/aws"


class RollbackAborted(RuntimeError):
    """Raised when the safety gate refuses execution."""


@dataclass
class _FakeProc:
    """Test double for subprocess.CompletedProcess.

    Lives in the production module (not test-only) so monkeypatched
    helpers can construct it without importing test internals.
    """

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


# ── shell wrappers ───────────────────────────────────────────────────────


def _kubectl(*args: str, capture: bool = True) -> subprocess.CompletedProcess:
    """Run kubectl. Captures by default — most callers parse stdout."""
    cmd = ["kubectl", *args]
    return subprocess.run(cmd, capture_output=capture, text=True, check=False)


# ── pure helpers ─────────────────────────────────────────────────────────


def previous_good_revision(history: list[dict]) -> Optional[str]:
    """Return the second-to-last revision that has a `deployedAt` timestamp.

    `history` is ArgoCD's `.status.history`, oldest-first. The newest entry
    is the current sync; the previous-good is the most-recent entry before
    it whose deploy actually completed.
    """
    completed = [h for h in history if h.get("deployedAt")]
    if len(completed) < 2:
        return None
    return completed[-2].get("revision")


def render_argocd_patch(target_revision: str) -> str:
    """JSON merge-patch payload for `kubectl patch ... --type=merge`."""
    return json.dumps({"spec": {"source": {"targetRevision": target_revision}}})


def parse_argocd_app(raw: str) -> dict:
    """Extract the fields rollback cares about from `kubectl get app -o json`.

    Returns {} on parse failure; callers treat empty dict as "couldn't read".
    """
    if not (raw or "").strip():
        return {}
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {
        "name": doc.get("metadata", {}).get("name", ""),
        "namespace": doc.get("metadata", {}).get("namespace", ""),
        "target_revision": doc.get("spec", {})
        .get("source", {})
        .get("targetRevision", ""),
        "current_revision": doc.get("status", {}).get("sync", {}).get("revision", ""),
        "history": doc.get("status", {}).get("history") or [],
    }


# ── safety gate ──────────────────────────────────────────────────────────


def assert_acked(ack_value: Optional[str]) -> None:
    """Raise RollbackAborted unless the operator passed the sentinel.

    Reads `ack_value` from the CLI flag if present, otherwise from the
    `ROLLBACK_ACK` env var. Either path must equal `ACK_SENTINEL` exactly.
    """
    import os

    effective = ack_value or os.environ.get("ROLLBACK_ACK")
    if effective != ACK_SENTINEL:
        raise RollbackAborted(
            f"refusing rollback without --ack={ACK_SENTINEL} "
            f"(or ROLLBACK_ACK={ACK_SENTINEL} env var)"
        )


# ── argocd subcommand ────────────────────────────────────────────────────


def rollback_argocd(
    app: str,
    ack: Optional[str],
    dry_run: bool,
    namespace: str = DEFAULT_NAMESPACE,
) -> int:
    """Revert an ArgoCD Application to its previous-good revision."""
    if not dry_run:
        try:
            assert_acked(ack)
        except RollbackAborted as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 1

    res = _kubectl(
        "-n", namespace, "get", "applications.argoproj.io", app, "-o", "json"
    )
    if res.returncode != 0:
        print(
            f"❌ kubectl get failed: {(res.stderr or '').strip().splitlines()[0:1]}",
            file=sys.stderr,
        )
        return 2

    parsed = parse_argocd_app(res.stdout)
    if not parsed:
        print(f"❌ couldn't parse Application {app}", file=sys.stderr)
        return 2

    target = previous_good_revision(parsed["history"])
    if not target:
        print(
            f"❌ no previous good revision in {app}'s history "
            f"(need >=2 deployed entries, found {len(parsed['history'])})",
            file=sys.stderr,
        )
        return 2

    patch = render_argocd_patch(target)

    print(f"  app:      {parsed['name']}")
    print(f"  current:  {parsed['current_revision']}")
    print(f"  revertTo: {target}")
    print(f"  patch:    {patch}")

    if dry_run:
        print("[DRY-RUN] would run: kubectl patch (no changes applied)")
        return 0

    res = _kubectl(
        "-n",
        namespace,
        "patch",
        "applications.argoproj.io",
        app,
        "--type=merge",
        "--patch",
        patch,
    )
    if res.returncode != 0:
        print(f"❌ kubectl patch failed: {res.stderr}", file=sys.stderr)
        return 2
    print(f"✅ patched {app} → targetRevision={target}")
    return 0


# ── terraform subcommand ────────────────────────────────────────────────


def rollback_terraform(
    target_tag: str,
    ack: Optional[str],
    dry_run: bool,
) -> int:
    """Revert the infra/aws tree to a known-good git tag and re-apply."""
    if not dry_run:
        try:
            assert_acked(ack)
        except RollbackAborted as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 1

    print(f"  target_tag: {target_tag}")
    print(f"  tf_dir:     {TF_DIR}")
    print(f"  command:    git checkout {target_tag} -- {TF_DIR}")
    print(f"  command:    cd {TF_DIR} && terraform apply -auto-approve")

    if dry_run:
        print(
            "[DRY-RUN] would run: git checkout + terraform apply (no changes applied)"
        )
        return 0

    co = subprocess.run(
        ["git", "checkout", target_tag, "--", TF_DIR],
        capture_output=True,
        text=True,
        check=False,
    )
    if co.returncode != 0:
        print(f"❌ git checkout {target_tag} failed: {co.stderr}", file=sys.stderr)
        return 2

    apply = subprocess.run(
        ["terraform", "apply", "-auto-approve"],
        cwd=TF_DIR,
        capture_output=False,
        text=True,
        check=False,
    )
    if apply.returncode != 0:
        print(
            "❌ terraform apply failed — see logs above; "
            "you may need to git checkout HEAD to restore the working tree",
            file=sys.stderr,
        )
        return 2
    print(f"✅ terraform reverted to {target_tag}")
    return 0


# ── status subcommand (read-only) ──────────────────────────────────────


def status_argocd(namespace: str = DEFAULT_NAMESPACE) -> int:
    """List Applications + their revertable revisions. No mutation."""
    res = _kubectl(
        "-n", namespace, "get", "applications.argoproj.io", "-A", "-o", "json"
    )
    if res.returncode != 0:
        print(f"❌ kubectl get failed: {res.stderr}", file=sys.stderr)
        return 2
    try:
        items = json.loads(res.stdout).get("items", [])
    except json.JSONDecodeError:
        print("❌ couldn't parse ArgoCD Applications response", file=sys.stderr)
        return 2

    if not items:
        print("(no ArgoCD Applications found)")
        return 0

    print(f"{'APP':<32} {'CURRENT':<12} {'REVERTABLE-TO':<12}")
    for app in items:
        parsed = parse_argocd_app(json.dumps(app))
        prev = previous_good_revision(parsed["history"]) or "—"
        cur = (parsed["current_revision"] or "?")[:12]
        print(f"{parsed['name']:<32} {cur:<12} {prev[:12]:<12}")
    return 0


# ── CLI dispatch ────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    arg = sub.add_parser(
        "argocd", help="Revert an ArgoCD Application to its previous good revision"
    )
    arg.add_argument("--app", default=DEFAULT_APP)
    arg.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    arg.add_argument("--ack", default=None, help=f"Set to {ACK_SENTINEL!r} to confirm")
    arg.add_argument(
        "--apply", action="store_true", help="Actually patch (default is dry-run)"
    )

    tf = sub.add_parser(
        "terraform", help="Revert infra/aws to a known-good git tag and re-apply"
    )
    tf.add_argument(
        "--tag", required=True, help="git tag to roll back to (e.g. v0.42.0)"
    )
    tf.add_argument("--ack", default=None)
    tf.add_argument("--apply", action="store_true")

    sub.add_parser(
        "status", help="List ArgoCD apps + their revertable revisions (read-only)"
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "status":
        return status_argocd()
    if args.cmd == "argocd":
        return rollback_argocd(
            app=args.app,
            ack=args.ack,
            dry_run=not args.apply,
            namespace=args.namespace,
        )
    if args.cmd == "terraform":
        return rollback_terraform(
            target_tag=args.tag,
            ack=args.ack,
            dry_run=not args.apply,
        )
    return 2  # pragma: no cover  # argparse rejects earlier


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
