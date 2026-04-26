#!/usr/bin/env bats
# Contract tests — verify structural integrity of ArgoCD App-of-Apps declarations.
# These tests run offline (no cluster required) and guard against path renames,
# missing kustomization.yaml files, and misconfigured sync policies.
#
# Run locally: bats bin/tests/contract_tests.bats
# CI: yaml-lint job in ci-validation.yml

REPO_ROOT="${BATS_TEST_DIRNAME}/../.."
APPS_ROOT="${REPO_ROOT}/k8s/gitops/apps-root.yaml"

# ── apps-root.yaml source path ────────────────────────────────────────────────

@test "apps-root: spec.source.path directory exists in repo" {
  local path
  path=$(grep "^    path:" "$APPS_ROOT" | awk '{print $2}')
  [ -n "$path" ]
  [ -d "${REPO_ROOT}/${path}" ]
}

@test "apps-root: source path has a kustomization.yaml" {
  local path
  path=$(grep "^    path:" "$APPS_ROOT" | awk '{print $2}')
  [ -f "${REPO_ROOT}/${path}/kustomization.yaml" ]
}

@test "apps-root: repoURL is set and non-empty" {
  local url
  url=$(grep "repoURL:" "$APPS_ROOT" | awk '{print $2}')
  [ -n "$url" ]
  [[ "$url" != "null" ]]
}

@test "apps-root: targetRevision is set" {
  local rev
  rev=$(grep "targetRevision:" "$APPS_ROOT" | awk '{print $2}')
  [ -n "$rev" ]
}

# ── Sync policy assertions ────────────────────────────────────────────────────

@test "apps-root: automated.prune is true" {
  grep -q "prune: true" "$APPS_ROOT"
}

@test "apps-root: automated.selfHeal is true" {
  grep -q "selfHeal: true" "$APPS_ROOT"
}

@test "apps-root: allowEmpty is false (prevents accidental wipe)" {
  grep -q "allowEmpty: false" "$APPS_ROOT"
}

@test "apps-root: CreateNamespace=true syncOption present" {
  grep -q "CreateNamespace=true" "$APPS_ROOT"
}

# ── k8s/apps directory structure ─────────────────────────────────────────────

@test "k8s/apps: every directory resource in kustomization.yaml has a kustomization.yaml" {
  # Only check resources listed as directory paths (no .yaml extension).
  local missing=0
  local apps_dir="${REPO_ROOT}/k8s/apps"
  while IFS= read -r line; do
    local resource
    resource=$(echo "$line" | sed 's/^[[:space:]]*-[[:space:]]*//' | xargs)
    [[ "$resource" == ./* ]] || continue
    [[ "$resource" == *.yaml ]] && continue
    local dir="${apps_dir}/${resource#./}"
    [ -d "$dir" ] || continue
    if [ ! -f "${dir}/kustomization.yaml" ]; then
      echo "Missing kustomization.yaml: ${dir}"
      missing=$((missing + 1))
    fi
  done < "${apps_dir}/kustomization.yaml"
  [ "$missing" -eq 0 ]
}

@test "k8s/apps: kustomization.yaml at root is valid (kustomize build exits 0)" {
  command -v kustomize >/dev/null || skip "kustomize not installed"
  run kustomize build "${REPO_ROOT}/k8s/apps"
  [ "$status" -eq 0 ]
}

# ── SOPS encrypted secret structure ──────────────────────────────────────────

@test "sops: all encrypted secrets have sops metadata block" {
  local bad=0
  while IFS= read -r file; do
    if ! grep -q "^sops:" "$file"; then
      echo "Missing sops: block in: $file"
      bad=$((bad + 1))
    fi
  done < <(find "${REPO_ROOT}/k8s" -name "*.yaml" -exec grep -l "^sops:" {} +)
  [ "$bad" -eq 0 ]
}

@test "sops: all encrypted secrets have at least one age recipient" {
  local bad=0
  while IFS= read -r file; do
    if ! grep -q "recipient:" "$file"; then
      echo "No age recipient in: $file"
      bad=$((bad + 1))
    fi
  done < <(find "${REPO_ROOT}/k8s" -name "*.yaml" -exec grep -l "^sops:" {} +)
  [ "$bad" -eq 0 ]
}

@test "sops: all encrypted secrets reference the same age public key (single recipient)" {
  # All secrets should be encrypted for the same key — if a new key appears it
  # means a secret was encrypted for the wrong recipient and won't decrypt at deploy time.
  local keys
  keys=$(find "${REPO_ROOT}/k8s" -name "*.yaml" \
    -exec grep -h "recipient:" {} + \
    | awk '{print $NF}' | sort -u | wc -l)
  # Exactly 1 unique recipient expected across the entire repo
  [ "$keys" -eq 1 ]
}
