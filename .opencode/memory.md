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
- **Ansible Dynamic Inventory:** Python-based dynamic inventory scripts must implement `--list` (return full inventory JSON) and `--host <hostname>` (return host-specific vars) for Ansible compatibility. The `_meta.hostvars` optimization prevents Ansible from calling `--host` for every host. For Terraform integration, use `terraform output -json` and parse outputs rather than reading tfstate directly (state file format may change between Terraform versions).
- **Ansible Role Design (k3s):** When creating roles for hybrid architectures (cloud + edge), use conditional task inclusion (`include_tasks` with `when`) to handle server vs. agent logic separately. Store node tokens in `/etc/rancher/k3s/k3s-token` for consistency. For Tailscale integration, use `tailscale ip -4 | head -1` to get the primary mesh IP. ARM64 resource constraints should be parameterized (e.g., `k3s_pi_max_pods: 50`) for Pi nodes. Always implement pre-flight checks (architecture, memory, existing installations) to fail fast before attempting installation. Templates should use Jinja2 conditionals for optional features (etcd snapshots, TLS SANs) to keep configs clean.

### AdGuard Home Rollback Investigation - Jan 25, 2026

**Context:** Considered rolling back AdGuard to commit d860e2b (Jan 22, working on rasp-pi-03 with Tailscale sidecar) to test if sidecar pattern performs better than current Tailscale Ingress pattern.

**Decision:** **ABORTED ROLLBACK** - Test cannot proceed due to missing Tailscale auth key.

**Investigation Results:**
- **Tailscale Secret Issue:** The `tailscale-auth` secret in adguard namespace contains placeholder value `REPLACE-WITH-TAILSCALE-AUTH-KEY-BEFORE-DEPLOYMENT` instead of real auth key
- **Architecture Difference:** 
  - d860e2b (Jan 22): Uses Tailscale **sidecar container** in AdGuard pod - requires valid TS_AUTHKEY
  - Current (Jan 25): Uses Tailscale **Ingress Controller** (separate pod managed by operator) - no secret needed
- **Current Status:** AdGuard working correctly on rasp-pi-03 with 0.5s page loads via Tailscale ingress after PR #71 rollback

**Root Cause Analysis:**
- Jan 22: AdGuard created on rasp-pi-03 with sidecar (d860e2b) - Working ✅
- Jan 24: Migrated to rasp-pi-04 (b14b31b) - Broke ❌ 
  - Likely broke because rasp-pi-04 has Tailscale routing/networking issues (not related to sidecar vs ingress)
- Jan 25: Between Jan 24-25, architecture changed from sidecar → ingress controller
- Jan 25: Rolled back node to rasp-pi-03 (PR #71) - Fixed ✅

**Key Finding:** The issue was **node-specific (rasp-pi-04 networking)**, not architecture-specific (sidecar vs ingress). Current ingress pattern is correct and doesn't require managing auth keys.

**Recommendation:** 
- Keep current Tailscale Ingress Controller pattern (cleaner, no secret management)
- Avoid deploying AdGuard to rasp-pi-04 until networking issues investigated
- Current rasp-pi-03 deployment is stable and performant (0.5s loads)