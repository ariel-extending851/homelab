# Project Memory & Lessons Learned
>
> This file is automatically updated by the agent to store context, recurring issues, and environment specifics.

- **Infrastructure:** Oracle Cloud VM.Standard3.Flex 2 instances (2 cores, 12GB RAM).
- **Network:** Tailscale mesh is the primary connectivity method.
- **Constraints:** Raspberry Pi nodes have limited I/O; avoid heavy concurrent disk writes.
- SearXNG latency is bound by the slowest engine; aggressive timeouts (1.5s) are required for hybrid-cloud stability.
- **Terraform State Migration:** When refactoring from singleton resources to `for_each` loops, use `terraform state mv` to rename resources (e.g., `github_branch_protection.main` → `github_branch_protection.default["main"]`). This avoids API errors and ensures zero-downtime updates.
- **Solo-Maintainer Challenge:** Branch protection with `require_last_push_approval = true` and `required_approving_review_count = 1` creates a chicken-and-egg problem for solo projects. Options: (a) use `--admin` flag if repo owner, (b) temporarily relax rules for merging, or (c) use a second account for reviews.
- **GitHub Actions Status Checks:** Branch protection contexts must match Check Run names exactly. Use "Pipeline Gate" pattern to aggregate multiple jobs into single required check.
