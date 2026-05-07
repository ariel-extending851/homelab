---
description: Incident response orchestration via the sre subagent. Runbook-first; requires human confirmation for destructive actions.
---

# Instructions

Orchestrates incident response on the homelab cluster. Reads the matching runbook before any action; gates destructive recovery on explicit human confirmation; opens the postmortem in the same PR as the fix.

## 1. Capture the symptom

If the user passed the symptom as an argument, use it. Otherwise, ask:

> What's broken? (e.g. "control plane unresponsive", "tailscale logged out", "argocd app <name> stuck", "<app> not responding")

## 2. Match a runbook

```bash
ls docs/runbooks/
git grep -l -i "<symptom-keywords>" docs/runbooks/
```

Print the matched runbook path. If none matches, instruct the SRE agent to **document the new failure mode after resolution** — `CLAUDE.md` § How we work here, rule 8.

## 3. Read-only diagnostics (auto, before delegating)

These are in `permissions.allow` and don't prompt:

```bash
make rollback-status        # ArgoCD apps + revertible revisions
make ansible-health         # cluster health
kubectl get nodes -o wide
kubectl get applications -n argocd
kubectl get pods -A | rg -v Running || true
tailscale status
```

Capture output for the SRE agent.

## 4. Delegate to the SRE agent

Invoke the `sre` subagent (Agent tool, `subagent_type: sre`) with:

- The symptom
- The matched runbook path (or instruction to draft a new one)
- The diagnostics output from step 3

The agent **proposes** actions; this command **executes** them only after confirmation.

## 5. Confirmation gate for destructive recovery

If the SRE agent proposes any of these, STOP and ask the user for explicit acknowledgement (`yes` / `apply`) before running:

- `make rollback-argocd APP=<name> APPLY=1` (default is DRY-RUN — always dry-run first)
- `make rollback-terraform ROLLBACK_TAG=vX.Y.Z APPLY=1`
- `make ansible-emergency`
- `terraform destroy`, `kubectl delete ns/<critical>`
- Anything `warn-destructive.sh` would block

## 6. Postmortem (after resolution)

Draft `docs/runbooks/<YYYY-MM-DD>-<incident-shortname>-postmortem.md` using `docs/runbooks/prod-deploy-2026-05-04-postmortem.md` as the template. Include:

- Symptom + timeline
- Root cause (or hypothesis if unconfirmed)
- Recovery steps actually taken
- What went well, what didn't
- Follow-ups (with PR links if any)

Save in the same PR as the code fix when there is one.

---

**Usage:**

```bash
/incident                                 # interactive — asks for symptom
/incident "control plane unresponsive"    # symptom passed as arg
/incident "argocd app golink stuck"
```

**Requirements:**

- `kubectl` access to the cluster (Tailscale up)
- Read access to `docs/runbooks/`
- Write access to `docs/runbooks/` for the postmortem
