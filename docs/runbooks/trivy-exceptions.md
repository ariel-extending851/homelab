# Trivy CVE Exception Process

The CI job `trivy-image-scan` runs `make test-trivy-strict` and **fails the
build on any HIGH/CRITICAL CVE that has an upstream fix available**. The job
is in `pipeline-gate-pr` and `pipeline-gate-nightly` `required_success` lists,
so a failure blocks merges.

There are **two** allowlist mechanisms — pick based on scope:

| Mechanism | File | When to use |
|---|---|---|
| Per-CVE | `.trivyignore` | A single CVE that you can't fix yet, but the rest of the image is current. |
| Per-image | `.trivy-image-allowlist.txt` | An image is pinned-but-known-vulnerable pending a planned upgrade. Findings reported, exit code suppressed. |

## When you need an exception

You hit a HIGH/CRITICAL fixable CVE in an upstream image (Grafana, Loki,
ArgoCD, etc.) and:

- The fix is not yet released in a tag your manifest can pin to, OR
- Pinning to the patched tag breaks the rest of the stack

## How to add a per-CVE exception

1. Identify the CVE ID from the Trivy report (CI artifact `trivy-reports`,
   under `.qa/trivy/<image>.json`).
2. Open a PR adding **one line** to `/.trivyignore` at repo root:

   ```text
   CVE-2025-12345  # grafana/grafana:11.x — upstream fix in 11.5.0 (ETA 2026-06) — review-by: 2026-07-15
   ```
3. **Required:** include `review-by: YYYY-MM-DD` (≤ 90 days out).
4. Get review from a second engineer — security-relevant change.
5. After merge, the CVE is suppressed only for that ID (other CVEs in the
   same image still block).

## How to add a per-image exception

For images pinned-but-known-vulnerable pending a planned upgrade (e.g.,
the whole observability stack at the time `test-trivy-strict` was first
enabled):

1. Open a tracking issue for the upgrade work.
2. PR adding **one line** to `/.trivy-image-allowlist.txt`:

   ```text
   grafana/grafana:10.2.3   # review-by: 2026-07-30  (Grafana 11 LTS upgrade — needs dashboard regression testing)
   ```

3. **Required:** include `review-by: YYYY-MM-DD` (≤ 90 days out) and a
   one-line justification.
4. Get review from a second engineer.

The image's findings still appear in the Trivy report and the CI logs
(prefixed `⚠️ ... (allowlisted)`), so they don't disappear from view.
They just don't fail the build.

## Re-evaluation

On the `review-by` date:
- Re-run `make test-trivy-strict` locally with the line removed.
- If upstream has patched: bump the image tag, remove the line.
- If still unpatched: extend the date with a fresh PR (and a fresh
  justification — don't just bump the date).

## Bypass for emergency hotfix

There is **no** emergency bypass. If you need to push a hotfix that
regresses on a CVE, the right move is:

1. Add the exception via the process above (single-line PR, fast review).
2. Merge that first.
3. Then merge the hotfix.

The Trivy gate is a deliberate safety check. Going around it defeats the
purpose; a one-line allowlist PR is faster than any bypass mechanism.
