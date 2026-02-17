## Plan

- [ ] Create branch from `develop` for TruffleHog workflow_dispatch/schedule fix.
- [ ] Update `.github/workflows/ci-validation.yml` to set TruffleHog base/head correctly for pull_request, push, workflow_dispatch, and schedule, guarding against all-zero `before` and identical base/head.
- [ ] Run CI Validation on the fix branch.
- [ ] Open PR targeting `develop` and ensure CI is green.
- [ ] Rerun CI Validation on `develop` to confirm Secret Scan passes post-merge.

> Do not remove completed tasks; mark with [x] when done.
