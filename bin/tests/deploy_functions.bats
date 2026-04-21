#!/usr/bin/env bats
# Unit tests for bin/deploy-aws-homelab.sh utility functions.
#
# Run locally: bats bin/tests/deploy_functions.bats
# CI: bats-core/bats-action@3.0.0 in ci-validation.yml

DEPLOY_SCRIPT="${BATS_TEST_DIRNAME}/../deploy-aws-homelab.sh"

# ── logging helpers ───────────────────────────────────────────────────────────

@test "log_info: outputs INFO prefix and message" {
  run bash -c "source '${DEPLOY_SCRIPT}'; log_info 'hello world'"
  [[ "$output" =~ "INFO" ]]
  [[ "$output" =~ "hello world" ]]
}

@test "log_success: outputs SUCCESS prefix" {
  run bash -c "source '${DEPLOY_SCRIPT}'; log_success 'all done'"
  [[ "$output" =~ "SUCCESS" ]]
  [[ "$output" =~ "all done" ]]
}

@test "log_error: outputs ERROR prefix" {
  run bash -c "source '${DEPLOY_SCRIPT}'; log_error 'something broke'"
  [[ "$output" =~ "ERROR" ]]
  [[ "$output" =~ "something broke" ]]
}

@test "log_warning: outputs WARNING prefix and message" {
  run bash -c "source '${DEPLOY_SCRIPT}'; log_warning 'watch out'"
  [[ "$output" =~ "WARNING" ]]
  [[ "$output" =~ "watch out" ]]
}

@test "error_exit: prints message and exits with status 1" {
  run bash -c "source '${DEPLOY_SCRIPT}'; error_exit 'fatal failure'"
  [ "$status" -eq 1 ]
  [[ "$output" =~ "fatal failure" ]]
}

# ── check_prerequisites ───────────────────────────────────────────────────────

_make_stub_bin() {
  # Creates a tmpdir with stub executables for the given tool names.
  local tmpbin
  tmpbin="$(mktemp -d)"
  for tool in "$@"; do
    printf '#!/bin/bash\nexit 0\n' > "$tmpbin/$tool"
    chmod +x "$tmpbin/$tool"
  done
  echo "$tmpbin"
}

@test "check_prerequisites: succeeds when all tools present and dirs exist" {
  local tmpbin
  tmpbin="$(_make_stub_bin terraform ansible-playbook aws sops)"
  local tf_dir ans_dir
  tf_dir="$(mktemp -d)"
  ans_dir="$(mktemp -d)"

  run bash -c "
    export PATH='$tmpbin'
    export SOPS_AGE_KEY='AGE-SECRET-KEY-1FAKE'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='$tf_dir' ANSIBLE_DIR='$ans_dir' check_prerequisites
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "All prerequisites met" ]]

  rm -rf "$tmpbin" "$tf_dir" "$ans_dir"
}

@test "check_prerequisites: exits 1 when terraform missing" {
  local tmpbin
  tmpbin="$(_make_stub_bin ansible-playbook aws)"
  local tf_dir ans_dir
  tf_dir="$(mktemp -d)"
  ans_dir="$(mktemp -d)"

  run bash -c "
    export PATH='$tmpbin'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='$tf_dir' ANSIBLE_DIR='$ans_dir' check_prerequisites
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Terraform" ]]

  rm -rf "$tmpbin" "$tf_dir" "$ans_dir"
}

@test "check_prerequisites: exits 1 when ansible-playbook missing" {
  local tmpbin
  tmpbin="$(_make_stub_bin terraform aws)"
  local tf_dir ans_dir
  tf_dir="$(mktemp -d)"
  ans_dir="$(mktemp -d)"

  run bash -c "
    export PATH='$tmpbin'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='$tf_dir' ANSIBLE_DIR='$ans_dir' check_prerequisites
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Ansible" ]]

  rm -rf "$tmpbin" "$tf_dir" "$ans_dir"
}

@test "check_prerequisites: exits 1 when TERRAFORM_DIR does not exist" {
  local tmpbin
  tmpbin="$(_make_stub_bin terraform ansible-playbook aws)"
  local ans_dir
  ans_dir="$(mktemp -d)"

  run bash -c "
    export PATH='$tmpbin'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='/no-such-dir-xyz' ANSIBLE_DIR='$ans_dir' check_prerequisites
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Terraform directory" ]]

  rm -rf "$tmpbin" "$ans_dir"
}

@test "check_prerequisites: exits 1 when ANSIBLE_DIR does not exist" {
  local tmpbin
  tmpbin="$(_make_stub_bin terraform ansible-playbook aws)"
  local tf_dir
  tf_dir="$(mktemp -d)"

  run bash -c "
    export PATH='$tmpbin'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='$tf_dir' ANSIBLE_DIR='/no-such-dir-xyz' check_prerequisites
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Ansible directory" ]]

  rm -rf "$tmpbin" "$tf_dir"
}

@test "check_prerequisites: exits 1 when aws binary missing" {
  local tmpbin
  tmpbin="$(_make_stub_bin terraform ansible-playbook)"
  local tf_dir ans_dir
  tf_dir="$(mktemp -d)"
  ans_dir="$(mktemp -d)"

  run bash -c "
    export PATH='$tmpbin'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='$tf_dir' ANSIBLE_DIR='$ans_dir' check_prerequisites
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "AWS CLI" ]]

  rm -rf "$tmpbin" "$tf_dir" "$ans_dir"
}

# ── wait_for_ssm ──────────────────────────────────────────────────────────────

@test "wait_for_ssm: returns 0 immediately when SSM reports Online" {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    aws() { echo 'Online'; }
    export -f aws
    TIMEOUT=30 wait_for_ssm 'i-fake123'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "SSM ready" ]]
}

@test "wait_for_ssm: returns 1 after all attempts when SSM never reports Online" {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    aws() { echo 'None'; }
    export -f aws
    sleep() { true; }
    export -f sleep
    TIMEOUT=30 wait_for_ssm 'i-fake456'
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Timeout" ]]
}

@test "wait_for_ssm: returns 0 on second attempt (SSM starts as None then Online)" {
  # Use a temp file to share state between command-substitution subshells.
  local flag_file
  flag_file="$(mktemp)"
  rm -f "$flag_file"  # absent on first call, present on subsequent calls

  run bash -c "
    source '${DEPLOY_SCRIPT}'
    aws() {
      if [ ! -f '$flag_file' ]; then
        touch '$flag_file'
        echo 'None'
      else
        echo 'Online'
      fi
    }
    export -f aws
    sleep() { true; }
    export -f sleep
    TIMEOUT=60 wait_for_ssm 'i-fakeretry'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "SSM ready" ]]
  rm -f "$flag_file"
}

# ── ssm_run (polling) ────────────────────────────────────────────────────────

@test "ssm_run: returns output when SSM status is Success on first poll" {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    aws() {
      case \"\$*\" in
        *send-command*)         echo 'cmd-abc123' ;;
        *'--query'\ 'Status'*) echo 'Success' ;;
        *StandardOutputContent*) echo 'instance output here' ;;
      esac
    }
    export -f aws
    sleep() { true; }
    export -f sleep
    ssm_run 'i-fake' 'echo hello'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "instance output here" ]]
}

@test "ssm_run: polls through InProgress before returning output" {
  local flag_file
  flag_file="\$(mktemp)"
  rm -f "\$flag_file"

  run bash -c "
    flag_file=\$(mktemp)
    rm -f \"\$flag_file\"
    source '${DEPLOY_SCRIPT}'
    aws() {
      case \"\$*\" in
        *send-command*) echo 'cmd-poll' ;;
        *'--query'\ 'Status'*)
          if [ ! -f \"\$flag_file\" ]; then
            touch \"\$flag_file\"
            echo 'InProgress'
          else
            echo 'Success'
          fi ;;
        *StandardOutputContent*) echo 'polled result' ;;
      esac
    }
    export -f aws
    sleep() { true; }
    export -f sleep
    ssm_run 'i-fake' 'slow-cmd'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "polled result" ]]
}

@test "ssm_run: returns output even when final status is Failed" {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    aws() {
      case \"\$*\" in
        *send-command*)          echo 'cmd-fail' ;;
        *'--query'\ 'Status'*)   echo 'Failed' ;;
        *StandardOutputContent*) echo 'partial output before fail' ;;
      esac
    }
    export -f aws
    sleep() { true; }
    export -f sleep
    ssm_run 'i-fake' 'failing-cmd'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "partial output before fail" ]]
}

# ── wait_for_tailscale_ip ─────────────────────────────────────────────────────

@test "wait_for_tailscale_ip: returns 0 when IP starts with 100." {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    ssm_run() { echo '100.64.0.42'; }
    export -f ssm_run
    TIMEOUT=30 wait_for_tailscale_ip 'i-fakenode'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ 100.64.0.42 ]]
}

@test "wait_for_tailscale_ip: returns 1 when IP is not in 100.0.0.0/8" {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    ssm_run() { echo '192.168.1.10'; }
    export -f ssm_run
    sleep() { true; }
    export -f sleep
    TIMEOUT=15 wait_for_tailscale_ip 'i-fakewrong'
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Timeout" ]]
}

@test "wait_for_tailscale_ip: returns 1 when ssm_run returns empty string" {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    ssm_run() { echo ''; }
    export -f ssm_run
    sleep() { true; }
    export -f sleep
    TIMEOUT=15 wait_for_tailscale_ip 'i-fakeempty'
  "
  [ "$status" -eq 1 ]
}

# ── check_sops_key ────────────────────────────────────────────────────────────

@test "check_sops_key: exits 1 when sops not in PATH" {
  run bash -c "
    export PATH=''
    source '${DEPLOY_SCRIPT}'
    check_sops_key
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "sops not found" ]]
}

@test "check_sops_key: exits 1 when sops present but no Age key configured" {
  local tmpbin
  tmpbin="$(_make_stub_bin sops)"

  run bash -c "
    export PATH='$tmpbin'
    unset SOPS_AGE_KEY
    unset SOPS_AGE_KEY_FILE
    source '${DEPLOY_SCRIPT}'
    check_sops_key
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Age key not configured" ]]

  rm -rf "$tmpbin"
}

@test "check_sops_key: succeeds when sops present, key set, and decryption passes" {
  local tmpbin
  tmpbin="$(mktemp -d)"
  # sops stub: exits 0 for any --decrypt call
  printf '#!/bin/bash\nexit 0\n' > "$tmpbin/sops"
  chmod +x "$tmpbin/sops"

  run bash -c "
    export PATH='$tmpbin'
    export SOPS_AGE_KEY='AGE-SECRET-KEY-1FAKE'
    source '${DEPLOY_SCRIPT}'
    check_sops_key
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "SOPS decryption verified" ]]

  rm -rf "$tmpbin"
}

# ── check_instance_count ──────────────────────────────────────────────────────

@test "check_instance_count: passes when exactly 2 instances are running" {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    check_instance_count 2
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Instance count verified: 2/2" ]]
}

@test "check_instance_count: aborts when more than 2 instances are running" {
  run bash -c "
    source '${DEPLOY_SCRIPT}'
    check_instance_count 3
  "
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Aborting to prevent orphans" ]]
}

# ── rewrite_kubeconfig ────────────────────────────────────────────────────────

@test "rewrite_kubeconfig: replaces 127.0.0.1 with Tailscale IP" {
  local fixture="${BATS_TEST_DIRNAME}/fixtures/test-kubeconfig.yaml"
  local dest
  dest="$(mktemp)"

  run bash -c "
    source '${DEPLOY_SCRIPT}'
    rewrite_kubeconfig \"\$(cat '${fixture}')\" '100.64.0.1' '${dest}'
    grep 'server' '${dest}'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ 100.64.0.1 ]]
  [[ ! "$output" =~ 127.0.0.1 ]]

  rm -f "$dest"
}

@test "rewrite_kubeconfig: content without 127.0.0.1 passes through unchanged" {
  local dest
  dest="$(mktemp)"

  run bash -c "
    source '${DEPLOY_SCRIPT}'
    rewrite_kubeconfig 'server: https://100.64.0.1:6443' '100.64.0.99' '${dest}'
    cat '${dest}'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ 100.64.0.1 ]]
  [[ ! "$output" =~ 100.64.0.99 ]]

  rm -f "$dest"
}

@test "rewrite_kubeconfig: sets file permissions to 0600" {
  local fixture="${BATS_TEST_DIRNAME}/fixtures/test-kubeconfig.yaml"
  local dest
  dest="$(mktemp)"

  run bash -c "
    source '${DEPLOY_SCRIPT}'
    rewrite_kubeconfig \"\$(cat '${fixture}')\" '100.64.0.2' '${dest}'
    stat -c '%a' '${dest}'
  "
  [ "$status" -eq 0 ]
  [[ "$output" =~ "600" ]]

  rm -f "$dest"
}

# ── destroy_infrastructure ────────────────────────────────────────────────────

@test "destroy_infrastructure: cancels without running terraform when user inputs 'no'" {
  local tmpbin workdir calllog
  tmpbin="$(mktemp -d)"
  workdir="$(mktemp -d)"
  calllog="${tmpbin}/terraform_calls.txt"

  printf '#!/bin/bash\necho "$@" >> "%s"\nexit 0\n' "${calllog}" > "${tmpbin}/terraform"
  chmod +x "${tmpbin}/terraform"
  printf '#!/bin/bash\nexit 0\n' > "${tmpbin}/ansible-playbook"
  chmod +x "${tmpbin}/ansible-playbook"

  run bash -c "
    export PATH='${tmpbin}:\$PATH'
    export TERRAFORM_DIR='${workdir}'
    export ANSIBLE_DIR='${workdir}'
    source '${DEPLOY_SCRIPT}'
    echo 'no' | destroy_infrastructure
  "
  [ "$status" -eq 0 ]
  [ ! -f "${calllog}" ] || ! grep -q "destroy" "${calllog}" 2>/dev/null

  rm -rf "${tmpbin}" "${workdir}"
}

@test "destroy_infrastructure: calls terraform destroy -auto-approve when user inputs 'yes'" {
  local tmpbin workdir calllog
  tmpbin="$(mktemp -d)"
  workdir="$(mktemp -d)"
  calllog="${tmpbin}/terraform_calls.txt"

  printf '#!/bin/bash\necho "$@" >> "%s"\nexit 0\n' "${calllog}" > "${tmpbin}/terraform"
  chmod +x "${tmpbin}/terraform"
  printf '#!/bin/bash\nexit 0\n' > "${tmpbin}/ansible-playbook"
  chmod +x "${tmpbin}/ansible-playbook"

  run bash -c "
    export PATH='${tmpbin}:\$PATH'
    export TERRAFORM_DIR='${workdir}'
    export ANSIBLE_DIR='${workdir}'
    source '${DEPLOY_SCRIPT}'
    echo 'yes' | destroy_infrastructure
  "
  [ "$status" -eq 0 ]
  grep -q "destroy -auto-approve" "${calllog}"

  rm -rf "${tmpbin}" "${workdir}"
}

# ── phase1_terraform ─────────────────────────────────────────────────────────

@test "phase1_terraform: runs init, validate, apply and refresh-only" {
  local tmpbin tfdir calllog
  tmpbin="$(mktemp -d)"
  tfdir="$(mktemp -d)"
  calllog="${tmpbin}/terraform_calls.txt"

  cat > "${tmpbin}/terraform" <<EOF
#!/bin/bash
if [ "\$1" = "state" ] && [ "\$2" = "list" ]; then
  echo "tailscale_acl.homelab_acl"
  exit 0
fi
echo "\$*" >> "${calllog}"
exit 0
EOF
  chmod +x "${tmpbin}/terraform"

  run bash -c "
    export PATH='${tmpbin}:\$PATH'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='${tfdir}' phase1_terraform
  "

  [ "$status" -eq 0 ]
  grep -q "init -upgrade" "${calllog}"
  grep -q "validate" "${calllog}"
  grep -q "apply -auto-approve" "${calllog}"
  grep -q "apply -refresh-only -auto-approve" "${calllog}"

  rm -rf "${tmpbin}" "${tfdir}"
}

@test "phase1_terraform: imports tailscale ACL when missing from state" {
  local tmpbin tfdir calllog
  tmpbin="$(mktemp -d)"
  tfdir="$(mktemp -d)"
  calllog="${tmpbin}/terraform_calls.txt"

  cat > "${tmpbin}/terraform" <<EOF
#!/bin/bash
if [ "\$1" = "state" ] && [ "\$2" = "list" ]; then
  # Empty output means ACL not yet in state.
  exit 0
fi
echo "\$*" >> "${calllog}"
exit 0
EOF
  chmod +x "${tmpbin}/terraform"

  run bash -c "
    export PATH='${tmpbin}:\$PATH'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='${tfdir}' phase1_terraform
  "

  [ "$status" -eq 0 ]
  grep -q "import tailscale_acl.homelab_acl acl" "${calllog}"

  rm -rf "${tmpbin}" "${tfdir}"
}

@test "phase1_terraform: exits 1 when terraform init fails" {
  local tmpbin tfdir
  tmpbin="$(mktemp -d)"
  tfdir="$(mktemp -d)"

  cat > "${tmpbin}/terraform" <<'EOF'
#!/bin/bash
if [ "$1" = "init" ]; then
  exit 1
fi
exit 0
EOF
  chmod +x "${tmpbin}/terraform"

  run bash -c "
    export PATH='${tmpbin}:\$PATH'
    source '${DEPLOY_SCRIPT}'
    TERRAFORM_DIR='${tfdir}' phase1_terraform
  "

  [ "$status" -eq 1 ]
  [[ "$output" =~ "Terraform init failed" ]]

  rm -rf "${tmpbin}" "${tfdir}"
}

# ── phase3_ansible ───────────────────────────────────────────────────────────

@test "phase3_ansible: validates inventory and runs site playbook" {
  local tmpbin ansdir calllog
  tmpbin="$(mktemp -d)"
  ansdir="$(mktemp -d)"
  calllog="${tmpbin}/ansible_calls.txt"

  cat > "${tmpbin}/python3" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "${tmpbin}/python3"

  cat > "${tmpbin}/ansible-playbook" <<EOF
#!/bin/bash
echo "\$*" >> "${calllog}"
exit 0
EOF
  chmod +x "${tmpbin}/ansible-playbook"

  cat > "${ansdir}/terraform_inventory_aws.py" <<'EOF'
#!/usr/bin/env python3
print('{}')
EOF

  run bash -c "
    export PATH='${tmpbin}:\$PATH'
    source '${DEPLOY_SCRIPT}'
    ANSIBLE_DIR='${ansdir}' phase3_ansible
  "

  [ "$status" -eq 0 ]
  grep -q -- "-i terraform_inventory_aws.py playbooks/site.yml" "${calllog}"

  rm -rf "${tmpbin}" "${ansdir}"
}

@test "phase3_ansible: exits 1 when inventory script is missing" {
  local ansdir
  ansdir="$(mktemp -d)"

  run bash -c "
    source '${DEPLOY_SCRIPT}'
    ANSIBLE_DIR='${ansdir}' phase3_ansible
  "

  [ "$status" -eq 1 ]
  [[ "$output" =~ "Dynamic inventory script not found" ]]

  rm -rf "${ansdir}"
}

@test "phase3_ansible: exits 1 when ansible-playbook fails" {
  local tmpbin ansdir
  tmpbin="$(mktemp -d)"
  ansdir="$(mktemp -d)"

  cat > "${tmpbin}/python3" <<'EOF'
#!/bin/bash
exit 0
EOF
  chmod +x "${tmpbin}/python3"

  cat > "${tmpbin}/ansible-playbook" <<'EOF'
#!/bin/bash
exit 1
EOF
  chmod +x "${tmpbin}/ansible-playbook"

  cat > "${ansdir}/terraform_inventory_aws.py" <<'EOF'
#!/usr/bin/env python3
print('{}')
EOF

  run bash -c "
    export PATH='${tmpbin}:\$PATH'
    source '${DEPLOY_SCRIPT}'
    ANSIBLE_DIR='${ansdir}' phase3_ansible
  "

  [ "$status" -eq 1 ]
  [[ "$output" =~ "Ansible playbook failed" ]]

  rm -rf "${tmpbin}" "${ansdir}"
}

# ── phase4_verify ────────────────────────────────────────────────────────────

@test "phase4_verify: writes kubeconfig with Tailscale endpoint when data is available" {
  local kubeconfig_path
  kubeconfig_path="/tmp/k3s-homelab-kubeconfig.yaml"
  rm -f "${kubeconfig_path}"

  run bash -c "
    source '${DEPLOY_SCRIPT}'
    K3S_SERVER_ID='i-server123'
    ssm_run() {
      case \"\$2\" in
        *'sudo cat /etc/rancher/k3s/k3s.yaml'*)
          cat <<'YAML'
apiVersion: v1
clusters:
- cluster:
    server: https://127.0.0.1:6443
  name: default
YAML
          ;;
        *'tailscale ip -4'*)
          echo '100.64.0.50'
          ;;
        *)
          echo 'ok'
          ;;
      esac
    }
    export -f ssm_run
    phase4_verify
    test -f '${kubeconfig_path}'
    grep -q '100.64.0.50' '${kubeconfig_path}'
    ! grep -q '127.0.0.1' '${kubeconfig_path}'
  "

  [ "$status" -eq 0 ]
  rm -f "${kubeconfig_path}"
}
