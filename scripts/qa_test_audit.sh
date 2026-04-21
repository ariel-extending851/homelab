#!/usr/bin/env bash
# QA evidence runner: executes test suites sequentially and writes auditable output.
# Usage:
#   bash scripts/qa_test_audit.sh
# Optional environment variables:
#   QA_INCLUDE_LIVE_E2E=1   Include make test-e2e-post-deploy (default: 0)
#   QA_OUT_DIR=.qa/evidence Output directory (default: .qa/evidence)

set -u

QA_INCLUDE_LIVE_E2E="${QA_INCLUDE_LIVE_E2E:-0}"
QA_OUT_DIR="${QA_OUT_DIR:-.qa/evidence}"

mkdir -p "${QA_OUT_DIR}"

RUN_TS_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
RUN_ID="$(date -u +"%Y%m%dT%H%M%SZ")"
COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")"
BRANCH_NAME="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"

SUMMARY_MD="${QA_OUT_DIR}/qa-audit-${RUN_ID}.md"
SUMMARY_LATEST_MD="${QA_OUT_DIR}/qa-audit-latest.md"
SUMMARY_JSON="${QA_OUT_DIR}/qa-audit-${RUN_ID}.json"
LOG_DIR="${QA_OUT_DIR}/logs-${RUN_ID}"
mkdir -p "${LOG_DIR}"

# Test matrix: id|command|required
# required=yes means it contributes to final failure.
TESTS=(
  "contracts|make test-contracts|yes"
  "terraform|make test-terraform|yes"
  "security|make test-security|yes"
  "disaster_recovery|make test-dr|no"
  "shell|make test-shell|yes"
  "python|make test-python|yes"
  "performance|make test-performance|no"
)

if [[ "${QA_INCLUDE_LIVE_E2E}" == "1" ]]; then
  TESTS+=("e2e_live|make test-e2e-post-deploy|yes")
else
  TESTS+=("e2e_live|make test-e2e-post-deploy|no")
fi

{
  printf "# QA Audit Report\n"
  printf "\n"
  printf -- "- Timestamp (UTC): %s\n" "${RUN_TS_UTC}"
  printf -- "- Commit: %s\n" "${COMMIT_SHA}"
  printf -- "- Branch: %s\n" "${BRANCH_NAME}"
  printf -- "- Include live E2E: %s\n" "${QA_INCLUDE_LIVE_E2E}"
  printf "\n"
  printf "| Suite | Command | Required | Status | Duration (s) | Log |\n"
  printf "|---|---|---|---|---:|---|\n"
} > "${SUMMARY_MD}"

# Build JSON manually to avoid external dependencies.
{
  printf "{\n"
  printf "  \"timestamp_utc\": \"%s\",\n" "${RUN_TS_UTC}"
  printf "  \"commit\": \"%s\",\n" "${COMMIT_SHA}"
  printf "  \"branch\": \"%s\",\n" "${BRANCH_NAME}"
  printf "  \"include_live_e2e\": \"%s\",\n" "${QA_INCLUDE_LIVE_E2E}"
  printf "  \"results\": [\n"
} > "${SUMMARY_JSON}"

required_failures=0
result_count=0

run_suite() {
  local suite_id="$1"
  local suite_cmd="$2"
  local required="$3"
  local log_file="${LOG_DIR}/${suite_id}.log"
  local skip_reason=""

  local start end duration status
  start="$(date +%s)"

  if [[ "${suite_id}" == "e2e_live" && "${QA_INCLUDE_LIVE_E2E}" != "1" ]]; then
    status="skipped"
    skip_reason="LIVE_E2E_DISABLED"
    : > "${log_file}"
    printf "Live E2E skipped by default. Set QA_INCLUDE_LIVE_E2E=1 to execute.\n" >> "${log_file}"
  else
    if bash -lc "${suite_cmd}" > "${log_file}" 2>&1; then
      status="passed"
    else
      status="failed"
    fi
  fi

  end="$(date +%s)"
  duration="$((end - start))"

  if [[ "${required}" == "yes" && "${status}" == "failed" ]]; then
    required_failures=$((required_failures + 1))
  fi

  printf "| %s | %s | %s | %s | %s | %s |\n" \
    "${suite_id}" "${suite_cmd}" "${required}" "${status}" "${duration}" "${log_file}" \
    >> "${SUMMARY_MD}"

  if [[ ${result_count} -gt 0 ]]; then
    printf ",\n" >> "${SUMMARY_JSON}"
  fi
  if [[ -n "${skip_reason}" ]]; then
    printf "    {\"suite\":\"%s\",\"command\":\"%s\",\"required\":\"%s\",\"status\":\"%s\",\"duration_seconds\":%s,\"log\":\"%s\",\"skip_reason\":\"%s\"}" \
      "${suite_id}" "${suite_cmd}" "${required}" "${status}" "${duration}" "${log_file}" "${skip_reason}" >> "${SUMMARY_JSON}"
  else
    printf "    {\"suite\":\"%s\",\"command\":\"%s\",\"required\":\"%s\",\"status\":\"%s\",\"duration_seconds\":%s,\"log\":\"%s\",\"skip_reason\":null}" \
      "${suite_id}" "${suite_cmd}" "${required}" "${status}" "${duration}" "${log_file}" >> "${SUMMARY_JSON}"
  fi
  result_count=$((result_count + 1))
}

for test_row in "${TESTS[@]}"; do
  IFS='|' read -r suite_id suite_cmd required <<< "${test_row}"
  echo "[QA] Running ${suite_id}: ${suite_cmd}"
  run_suite "${suite_id}" "${suite_cmd}" "${required}"
done

{
  printf "\n  ],\n"
  printf "  \"required_failures\": %s\n" "${required_failures}"
  printf "}\n"
} >> "${SUMMARY_JSON}"

cp "${SUMMARY_MD}" "${SUMMARY_LATEST_MD}"

echo ""
echo "QA evidence generated:"
echo "- ${SUMMARY_MD}"
echo "- ${SUMMARY_JSON}"
echo "- ${LOG_DIR}/"

if [[ ${required_failures} -gt 0 ]]; then
  echo ""
  echo "[QA] Required suites failed: ${required_failures}"
  exit 1
fi

echo ""
echo "[QA] All required suites passed (or were intentionally skipped when non-required)."
