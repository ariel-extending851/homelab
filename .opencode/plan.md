## Plan

- [ ] Create branch from `develop` for TruffleHog workflow_dispatch/schedule fix.
- [ ] Update `.github/workflows/ci-validation.yml` to set TruffleHog base/head correctly for pull_request, push, workflow_dispatch, and schedule, guarding against all-zero `before` and identical base/head.
- [ ] Run CI Validation on the fix branch.
- [ ] Open PR targeting `develop` and ensure CI is green.
- [ ] Rerun CI Validation on `develop` to confirm Secret Scan passes post-merge.
- [x] Fix YAML inventory empty groups (aws_instances, k3s_server, amd64_nodes) to remove/convert them so Ansible stops emitting the phantom `{` host.
- [x] Ensure mock AWS inventory parses with the JSON plugin (or convert to YAML) so `{` is not added to ungrouped.
- [x] Re-run `ansible-inventory --graph` and `ansible-playbook --list-hosts` to confirm no phantom `{` host.
- [x] Re-run `make hybrid-dry-run-ansible` and confirm no inventory parse warnings (may need extended timeout).
- [x] Validate banner shows 4 intended hosts and phantom `{` host is gone.
- [ ] Add mock_aws group vars (local connection + mock_inventory flag) to avoid SSH timeouts in dry-run.
- [ ] Exclude mock_aws from plays that would run remote actions (tailscale, k3s, argocd, health checks).
- [ ] Re-run `make hybrid-dry-run-ansible` to confirm no SSH timeouts and safe local-only execution.

> Do not remove completed tasks; mark with [x] when done.
