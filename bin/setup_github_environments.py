#!/usr/bin/env python3
"""Idempotent provisioning of GitHub Environments referenced by ci-deployment.yml.

Creates / updates three environments:
  - staging-deploy        : no reviewers; ephemeral staging workspace
  - production-approval   : 1+ required reviewer + 5min wait timer; gate before prod
  - production            : runtime env for prod terraform-apply, ansible-deploy, rollback

ci-deployment.yml already references these by name; without them the GitHub
jobs run unattended on push to main. This script creates them via `gh api`
(idempotent: re-running just updates settings).

Required: gh CLI authenticated as a repo admin.

Usage:
  python3 bin/setup_github_environments.py
  python3 bin/setup_github_environments.py --reviewers alice,bob
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ENV_STAGING = "staging-deploy"
ENV_PROD_APPROVAL = "production-approval"
ENV_PROD = "production"
PROD_WAIT_TIMER_MIN = 5


# ── gh CLI wrappers (subprocess; the established repo pattern) ─────────────


def gh_api(args, input_str=None):
    """Run `gh api <args>` and return stdout. Raise on non-zero exit with stderr surfaced."""
    res = subprocess.run(
        ["gh", "api", *args],
        capture_output=True,
        text=True,
        input=input_str,
    )
    if res.returncode != 0:
        msg = (res.stderr or res.stdout or "").strip()
        raise RuntimeError(f"gh api {' '.join(args)} failed: {msg}")
    return res.stdout


def repo_slug():
    """Return the current repo's nameWithOwner (e.g. 'octocat/Hello-World')."""
    return subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def repo_owner():
    """Return the owner login of the current repo."""
    return subprocess.run(
        ["gh", "repo", "view", "--json", "owner", "-q", ".owner.login"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def resolve_user_id(username):
    """Resolve a GitHub username to its numeric ID via `gh api users/<u>`."""
    out = gh_api([f"users/{username}"])
    return int(json.loads(out)["id"])


# ── pure helpers (testable without subprocess) ─────────────────────────────


def reviewer_payload(usernames, id_resolver):
    """Build the `reviewers` array from a comma-separated `usernames` string.

    `id_resolver(username) -> int` is injected so tests don't hit `gh`.
    """
    out = []
    for u in usernames.split(","):
        u = u.strip()
        if not u:
            continue
        out.append({"type": "User", "id": id_resolver(u)})
    return out


def env_body_staging():
    return {"wait_timer": 0, "reviewers": [], "deployment_branch_policy": None}


def env_body_production_approval(reviewers):
    return {
        "wait_timer": PROD_WAIT_TIMER_MIN,
        "reviewers": reviewers,
        "deployment_branch_policy": {
            "protected_branches": True,
            "custom_branch_policies": False,
        },
    }


def env_body_production():
    return {
        "wait_timer": 0,
        "reviewers": [],
        "deployment_branch_policy": {
            "protected_branches": True,
            "custom_branch_policies": False,
        },
    }


# ── orchestration ──────────────────────────────────────────────────────────


def put_env(slug, name, body):
    """PUT /repos/<slug>/environments/<name> with the given JSON body."""
    print(f"→ {name}")
    gh_api(
        [
            "-X",
            "PUT",
            f"repos/{slug}/environments/{name}",
            "-H",
            "Accept: application/vnd.github+json",
            "--input",
            "-",
        ],
        input_str=json.dumps(body),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reviewers",
        default=os.environ.get("GH_REVIEWERS"),
        help=(
            "Comma-separated usernames to require as reviewers on "
            f"{ENV_PROD_APPROVAL}. Defaults to the repo owner."
        ),
    )
    args = parser.parse_args(argv)

    slug = repo_slug()
    reviewers_str = args.reviewers or repo_owner()
    print(f"Repo: {slug}")
    print(f"Reviewers for {ENV_PROD_APPROVAL}: {reviewers_str}")
    print()

    reviewers = reviewer_payload(reviewers_str, resolve_user_id)

    put_env(slug, ENV_STAGING, env_body_staging())
    put_env(slug, ENV_PROD_APPROVAL, env_body_production_approval(reviewers))
    put_env(slug, ENV_PROD, env_body_production())

    print()
    print("Verification:")
    raw = gh_api([f"repos/{slug}/environments"])
    data = json.loads(raw)
    for env in data.get("environments", []):
        rules = env.get("protection_rules", [])
        wait = next((r["wait_timer"] for r in rules if r["type"] == "wait_timer"), 0)
        n_reviewers = next(
            (
                len(r.get("reviewers", []))
                for r in rules
                if r["type"] == "required_reviewers"
            ),
            0,
        )
        print(f"  ✓ {env['name']:<22} wait_timer={wait}  reviewers={n_reviewers}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
