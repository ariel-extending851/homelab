# QA DevOps Test Maturity Roadmap (30 Days)

## Executive Summary

Current state is strong for offline validation and static guardrails, with evidence-based audits already in place.

The next maturity jump is to increase confidence in production-like behavior, resilience, and recovery execution.

### Current Maturity Snapshot

1. Test orchestration: strong (Makefile as source of truth)
2. Static and offline validation: strong (Terraform, Ansible, K8s policy, shell, Python)
3. Recovery and resilience execution: medium (readiness checks exist, live execution is still optional)
4. Security depth: medium (good guardrails, limited runtime/supply-chain depth)

### 30-Day Target

Reach high confidence for DevOps QA with measurable gates:

1. Required test pass rate >= 98%
2. Flake rate <= 2%
3. Mean time to detect failure <= 10 min (CI)
4. Recovery drill success >= 95%
5. Recovery RTO <= 45 min in drill environment
6. Live E2E required at least nightly (or on release candidate)

---

## Scope

This roadmap focuses on:

1. Reliability of pipelines and suites
2. Live-ish validation without Raspberry Pi dependency where possible
3. Disaster recovery execution (not only readiness)
4. Security runtime and supply-chain checks
5. Test observability and quality metrics

Out of scope for this cycle:

1. Large architecture redesign
2. Full chaos engineering platform rollout

---

## Week 1 (Days 1-7): Baseline and Reliability Hardening

### Objectives

1. Stabilize all existing suites and make outcomes fully observable
2. Remove remaining non-determinism and ambiguous skip behavior

### Deliverables

1. Standardized test profiles in Makefile:
- `test-offline-required`
- `test-offline-extended`
- `test-live-required` (nightly or RC)

2. QA scorecard artifact generated per run:
- pass rate
- flake rate
- durations per suite
- skipped-required count

3. Skip policy:
- Required suites cannot be skipped silently
- Skips must include reason codes

### Implementation Tasks

1. Add an aggregate scorecard generator in `.qa/evidence/` from existing audit JSON.
2. Add a CI gate that fails when any required suite is skipped.
3. Persist a rolling 14-run history for trend checks.
4. Set per-suite timeout thresholds and fail when exceeded by a fixed margin.

### Exit Criteria

1. All required offline suites green for 5 consecutive runs
2. No unexplained skip in required suites
3. Scorecard visible in CI artifacts for every run

---

## Week 2 (Days 8-14): Recovery and Rollback Execution

### Objectives

1. Move from DR readiness checks to DR execution evidence
2. Validate rollback paths under controlled failure

### Deliverables

1. Scheduled DR drill (at least weekly) in a non-production environment
2. Automated rollback test for at least one critical deployment path
3. Recovery report with measured RTO and recovery checklist completion

### Implementation Tasks

1. Create `make test-dr-drill` target that performs:
- pre-check snapshot
- controlled failure simulation
- recovery playbook execution
- post-recovery validation

2. Add `make test-rollback-critical` target for one key app path.
3. Record `started_at`, `recovered_at`, and computed RTO in evidence JSON.
4. Fail gate when RTO exceeds threshold.

### Exit Criteria

1. At least 2 successful DR drills with evidence
2. Rollback path validated end-to-end at least once per week
3. RTO meets target in drill environment

---

## Week 3 (Days 15-21): Security Runtime and Supply Chain

### Objectives

1. Expand security testing beyond static guardrails
2. Increase confidence in image/dependency/runtime posture

### Deliverables

1. Container image vulnerability gate for critical workloads
2. Dependency and IaC security scan integrated in CI
3. Minimal runtime security assertions for critical pods/services

### Implementation Tasks

1. Add `make test-security-runtime` for runtime assertions (non-root, privilege escalation blocked, read-only FS where applicable).
2. Add `make test-security-supply-chain` for image/dependency scanning.
3. Define severity thresholds (for example: fail on critical, warn on high with tracked exceptions).
4. Store exception list with owner and expiration date.

### Exit Criteria

1. Security runtime suite green in required profile
2. No untracked critical vulnerabilities in required components
3. Exceptions are time-bounded and documented

---

## Week 4 (Days 22-30): Production-Like Confidence and Anti-Flake

### Objectives

1. Enforce live E2E confidence for release rhythm
2. Reduce flakiness and improve trust in failed builds

### Deliverables

1. Nightly required live E2E gate (or release-candidate gate)
2. Flake triage workflow with quarantine policy and SLA
3. Final QA maturity report against targets

### Implementation Tasks

1. Promote `test-e2e-post-deploy` from optional to required for nightly/RC workflow.
2. Add auto-rerun-once only for known flaky class, with explicit labeling.
3. Build flake dashboard from last 14 runs.
4. Run one controlled game day scenario and capture incident-style timeline.

### Exit Criteria

1. Live E2E required gate passing for 5 nightly runs
2. Flake rate <= 2%
3. QA maturity report shows target compliance or explicit gap list

---

## QA DevOps Scorecard

Use this scorecard each week:

1. Required pass rate: target >= 98%
2. Required skip rate: target = 0%
3. Flake rate: target <= 2%
4. Mean suite duration variance: target <= 20%
5. DR drill success: target >= 95%
6. Recovery RTO: target <= 45 min
7. Critical vulnerability backlog: target = 0 untracked

---

## Suggested Makefile Additions

1. `test-offline-required`
2. `test-offline-extended`
3. `test-live-required`
4. `test-dr-drill`
5. `test-rollback-critical`
6. `test-security-runtime`
7. `test-security-supply-chain`
8. `qa-scorecard`
9. `qa-flake-report`
10. `qa-gameday-report`

---

## Risks and Mitigations

1. Risk: Live tests unstable due to environment drift
- Mitigation: Preflight checks and immutable test environment baseline

2. Risk: Long CI time reduces adoption
- Mitigation: Split required vs extended profiles and parallelize non-blocking suites

3. Risk: False positives in security scans
- Mitigation: Exception process with expiration and owner accountability

4. Risk: DR drill fatigue
- Mitigation: Lightweight scripted drills with fixed cadence and rotating ownership

---

## Definition of Done (End of 30 Days)

The project reaches a high maturity QA DevOps posture when all are true:

1. Offline required profile is consistently green
2. Nightly or RC live required profile is consistently green
3. DR execution is measured and within target RTO
4. Security runtime and supply chain gates are enforced
5. Flake and trend metrics are visible and acted upon
6. Evidence artifacts are generated automatically and reviewed weekly

---

## First 72 Hours (Quick Start)

1. Create the new Makefile profile targets and wire them in CI.
2. Implement `qa-scorecard` based on existing `.qa/evidence/qa-audit-*.json`.
3. Add required-skip fail gate in workflow.
4. Schedule first DR drill and define RTO threshold.
5. Mark owner per workstream: Reliability, DR, Security, E2E.
