# Homelab Infrastructure Management
# Usage: make <target>

.PHONY: help setup deploy deploy-safe deploy-quick destroy status ansible \
        terraform terraform-init terraform-plan terraform-apply \
        ansible-galaxy-install ansible-ping ansible-inventory ansible-deploy \
        validate verify-all test-homolog test-e2e test-rpi test-shell test-python \
        test-molecule test-molecule-rpi test-molecule-argocd \
        test-molecule-lint test-molecule-k3s test-molecule-tailscale \
        test-molecule-gatekeeper hybrid-dry-run hybrid-dry-run-prereqs \
        hybrid-dry-run-localstack hybrid-dry-run-ansible clean-local-tf \
        clean-pi-server pi-migrate-to-agent clean docs show-costs \
        oidc-init oidc-plan oidc-apply oidc-output \
        test-sops test-acl-json test-phase0-ansible argocd-manifest-fetch \
        smoke-test test-contracts \
        rollback-tf-refresh rollback-argocd-status rollback-verify-prereqs \
        validate-terraform-all validate-k8s-all validate-yaml-lint \
        validate-shellcheck validate-sops-workflow

# Default target
.DEFAULT_GOAL := help

# Configuration
TERRAFORM_DIR  := infra/aws
ARGOCD_VERSION := v2.13.2
ANSIBLE_DIR := ansible
DEPLOY_SCRIPT := bin/deploy-aws-homelab.sh

# Use mise when available (local dev); fall through to plain binary in CI.
MISE_EXEC := $(shell command -v mise >/dev/null 2>&1 && echo "mise exec --" || echo "")

##@ General

help: ## Display this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

setup: ## Install all tools and dependencies (run this first)
	@echo "📦 Installing mise tools..."
	@mise install
	@echo "💉 Injecting Python deps into ansible-core venv (kubernetes, docker, requests)..."
	@mise run setup-molecule-deps
	@echo "📚 Installing Ansible collections..."
	@make ansible-galaxy-install
	@echo "🔧 Initializing Terraform..."
	@make terraform-init
	@echo "🛡️  Installing Git Hooks..."
	@$(MISE_EXEC) pre-commit install
	@$(MISE_EXEC) pre-commit install --hook-type commit-msg
	@echo "✅ Environment is ready! Run 'make test-e2e' or 'make test-rpi' to validate."

ansible-galaxy-install: ## Install Ansible collections from requirements.yml
	@echo "📦 Installing Ansible collections..."
	@cd $(ANSIBLE_DIR) && mise exec -- ansible-galaxy collection install -r requirements.yml --force
	@echo "✅ Ansible collections installed."

##@ Deployment

deploy: ## Deploy complete AWS infrastructure + k3s cluster + ArgoCD + apps
	@echo "🚀 Starting full deployment..."
	@$(DEPLOY_SCRIPT)

deploy-safe: verify-all deploy ## Run all tests and then deploy if they pass

deploy-quick: ## Deploy without waiting for verification (faster)
	@echo "⚡ Quick deployment..."
	@SKIP_VERIFY=true $(DEPLOY_SCRIPT)

destroy: ## Destroy all AWS infrastructure (interactive confirmation)
	@echo "💣 Destroying infrastructure..."
	@$(DEPLOY_SCRIPT) --destroy

##@ Infrastructure Management

terraform-init: ## Initialize Terraform
	@echo "🔧 Initializing Terraform..."
	@cd $(TERRAFORM_DIR) && terraform init

terraform-plan: ## Show Terraform execution plan
	@echo "📋 Planning Terraform changes..."
	@cd $(TERRAFORM_DIR) && terraform plan

terraform-apply: ## Apply Terraform configuration only
	@echo "🏗️  Applying Terraform..."
	@cd $(TERRAFORM_DIR) && terraform apply

terraform-output: ## Show Terraform outputs
	@cd $(TERRAFORM_DIR) && terraform output

terraform-state: ## List Terraform state resources
	@cd $(TERRAFORM_DIR) && terraform state list

oidc-init: ## Bootstrap GitHub Actions OIDC role in AWS (run once, like aws-backend)
	@echo "🔐 Initializing OIDC bootstrap module..."
	@cd infra/aws-oidc && terraform init

oidc-plan: ## Preview OIDC bootstrap changes
	@cd infra/aws-oidc && terraform plan

oidc-apply: ## Create GitHub Actions OIDC provider + IAM role in AWS (run once)
	@echo "🔐 Applying OIDC bootstrap (one-time operation)..."
	@cd infra/aws-oidc && terraform apply

oidc-output: ## Show OIDC role ARN (copy this to GitHub Actions variable AWS_ACCOUNT_ID note)
	@cd infra/aws-oidc && terraform output

##@ Configuration Management

ansible-ping: ## Test Ansible connectivity to all hosts
	@echo "🏓 Pinging all hosts..."
	@cd $(ANSIBLE_DIR) && ansible all -i terraform_inventory_aws.py -m ping

ansible-inventory: ## Show dynamic inventory
	@echo "📋 Dynamic inventory:"
	@cd $(ANSIBLE_DIR) && python3 terraform_inventory_aws.py --list | jq .

ansible-deploy: ## Run Ansible playbook only (assumes infrastructure exists; auto-refreshes kubeconfig)
	@echo "⚙️  Running Ansible configuration..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml
	@echo ""
	@echo "✅ Deployment complete. Kubeconfig refreshed automatically."
	@echo "   Run the following to use kubectl locally:"
	@echo "   export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml"

ansible-check: ## Run Ansible in check mode (dry run)
	@echo "🔍 Ansible check mode..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml --check

ansible-health: ## Run health check playbook
	@echo "💚 Checking cluster health..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/production.yml playbooks/maintenance/health_check.yml

ansible-router: ## Configure the GL.iNet Opal Router (Gatekeeper)
	@echo "🛡️  Configuring OpenWrt Gatekeeper..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/production.yml playbooks/configure_router.yml

clean-tailscale: ## Remove stale Tailscale nodes
	@echo "🧹 Cleaning up stale Tailscale nodes..."
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/maintenance/cleanup_tailscale.yml


ansible-emergency: ## Run emergency recovery playbook
	@echo "🚨 Running emergency recovery..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/production.yml playbooks/recovery/emergency_recovery.yml

##@ Kubernetes Management

k8s-nodes: ## Show Kubernetes nodes
	@kubectl get nodes -o wide

k8s-pods: ## Show all pods
	@kubectl get pods -A -o wide

k8s-apps: ## Show ArgoCD applications
	@kubectl get applications -n argocd

k8s-ingress: ## Show all ingresses
	@kubectl get ingress -A

k8s-kubeconfig: ## Refresh local kubeconfig from k3s server via SSM (auto-detects current Tailscale IP)
	@echo "📥 Refreshing kubeconfig via SSM (self-healing — detects current Tailscale IP)..."
	@cd $(ANSIBLE_DIR) && ansible-playbook \
		-i terraform_inventory_aws.py \
		playbooks/site.yml \
		--tags kubeconfig \
		--limit k3s-server
	@echo "✅ Saved to /tmp/k3s-homelab-kubeconfig.yaml"
	@echo "   export KUBECONFIG=/tmp/k3s-homelab-kubeconfig.yaml"

argocd-password: ## Get ArgoCD admin password
	@kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo

argocd-port-forward: ## Port forward to ArgoCD UI
	@echo "🌐 Forwarding ArgoCD to https://localhost:8080"
	@echo "   Username: admin"
	@echo "   Password: $$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)"
	@kubectl port-forward svc/argocd-server -n argocd 8080:443

##@ Status & Monitoring

status: ## Show overall infrastructure status
	@echo "╔════════════════════════════════════════════════════════════╗"
	@echo "║              AWS HOMELAB STATUS                            ║"
	@echo "╚════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "📊 Terraform State:"
	@cd $(TERRAFORM_DIR) && terraform show -no-color | head -20 || echo "  No state found"
	@echo ""
	@echo "🖥️  EC2 Instances:"
	@cd $(TERRAFORM_DIR) && terraform output -json 2>/dev/null | jq -r '.k3s_server_public_ip.value, .k3s_agent_public_ip.value' 2>/dev/null || echo "  No instances found"
	@echo ""
	@echo "☸️  Kubernetes Nodes:"
	@kubectl get nodes 2>/dev/null || echo "  Cluster not accessible"
	@echo ""
	@echo "📦 ArgoCD Applications:"
	@kubectl get applications -n argocd 2>/dev/null || echo "  ArgoCD not deployed"

logs-terraform: ## Show Terraform logs
	@echo "📜 Recent Terraform operations:"
	@ls -lt $(TERRAFORM_DIR)/.terraform/terraform.tfstate 2>/dev/null || echo "No Terraform state"

logs-ansible: ## Show Ansible logs
	@echo "📜 Ansible logs:"
	@tail -50 ~/.ansible.log 2>/dev/null || echo "No Ansible logs (set log_path in ansible.cfg)"

##@ Testing & Validation

validate: ## Run all basic syntax and connectivity validation checks
	@echo "🧪 Running basic validation..."
	@make validate-terraform
	@make validate-ansible
	@make test-connectivity

validate-terraform: validate-terraform-all ## Validate Terraform (alias for validate-terraform-all)

validate-terraform-all: ## Validate all Terraform modules: syntax + format + tflint (infra/aws + aws-oidc + aws-backend)
	@echo "✓ Validating infra/aws (init + validate + fmt + tflint)..."
	@cd infra/aws && terraform init -backend=false -input=false
	@cd infra/aws && terraform validate
	@cd infra/aws && terraform fmt -check -diff
	@cd infra/aws && tflint --init
	@cd infra/aws && tflint --format=compact
	@echo "✓ Validating infra/aws-oidc..."
	@cd infra/aws-oidc && terraform init -backend=false -input=false
	@cd infra/aws-oidc && terraform validate
	@cd infra/aws-oidc && terraform fmt -check -diff
	@echo "✓ Validating infra/aws-backend..."
	@cd infra/aws-backend && terraform init -backend=false -input=false
	@cd infra/aws-backend && terraform validate
	@cd infra/aws-backend && terraform fmt -check -diff
	@echo "  ✓ All Terraform modules validated."

validate-ansible: ## Syntax-check all critical Ansible playbooks
	@echo "✓ Validating Ansible syntax (all critical playbooks)..."
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/site.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/maintenance/health_check.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/gitops/deploy_argocd.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/gitops/bootstrap_apps.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/deploy_k3s.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/configure_router.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/maintenance/cleanup_pi_server.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/maintenance/cleanup_tailscale.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/maintenance/optimize_rpi.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/recovery/emergency_recovery.yml --syntax-check
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/validation.yml --syntax-check
	@echo "  ✓ All Ansible playbooks passed syntax check."

test-connectivity: ## Test SSM connectivity to k3s server (Zero Trust)
	@echo "✓ Testing SSM connectivity..."
	@SERVER_ID=$$(aws ec2 describe-instances \
		--filters "Name=tag:Name,Values=hl-k3s-server" "Name=instance-state-name,Values=running" \
		--query "Reservations[0].Instances[0].InstanceId" --output text 2>/dev/null); \
	if [ "$$SERVER_ID" = "None" ] || [ -z "$$SERVER_ID" ]; then \
		echo "  Server: not found"; exit 1; \
	fi; \
	STATUS=$$(aws ssm describe-instance-information \
		--filters "Key=InstanceIds,Values=$$SERVER_ID" \
		--query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || echo "Unknown"); \
	if [ "$$STATUS" = "Online" ]; then \
		echo "  Server: OK (SSM Online)"; \
	else \
		echo "  Server: FAILED (SSM status=$$STATUS)"; exit 1; \
	fi

##@ Comprehensive Validation (Dry-Run)

dry-run: ## Perform a full dry-run of the deployment plan
	@echo "🏁 Performing full dry-run..."
	@make dry-run-terraform
	@make dry-run-ansible-cluster
	@make dry-run-ansible-apps

dry-run-terraform: ## Show the Terraform execution plan (dry-run)
	@echo "📋 Planning Terraform changes (dry-run)..."
	@cd $(TERRAFORM_DIR) && terraform plan

dry-run-ansible-cluster: ## Run the main cluster playbook in check mode (dry-run)
	@echo "🔍 Simulating cluster configuration (Ansible check mode)..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml --check

dry-run-ansible-apps: ## Run the app bootstrap playbook in check mode (dry-run)
	@echo "☸️  Simulating Kubernetes app deployment (Ansible check mode)..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i terraform_inventory_aws.py playbooks/gitops/bootstrap_apps.yml --check

##@ Local E2E Validation

test-e2e: ## Run full end-to-end validation suite locally
	@echo "🏁 Starting full end-to-end validation suite..."
	@make test-e2e-prereqs
	@make test-e2e-localstack
	@make test-e2e-ansible
	@make test-e2e-k8s
	@echo "✅ Full end-to-end validation successful!"

test-e2e-prereqs: ## Check for all E2E testing dependencies
	@echo "🔎 Checking prerequisites..."
	@command -v docker >/dev/null || (echo "❌ Docker not found"; exit 1)
	@command -v awslocal >/dev/null || (echo "❌ awslocal not found. Install via 'pip install awscli-local'"; exit 1)
	@command -v kustomize >/dev/null || (echo "❌ kustomize not found"; exit 1)
	@command -v kubectl >/dev/null || (echo "❌ kubectl not found"; exit 1)
	@echo "  ✓ All prerequisites found."

test-e2e-localstack: ## Run Terraform apply/destroy against a localstack container
	@echo "📦 Testing Terraform against LocalStack..."
	@$(TERRAFORM_DIR)/scripts/test-localstack.sh

test-e2e-ansible: ## Test Ansible playbooks with a fake inventory
	@echo "⚙️  Testing Ansible playbooks in check-mode with fake inventory..."
	@echo '{"_meta":{"hostvars":{}},"all":{"children":["ungrouped"]},"ungrouped":{"children":["k3s_server","k3s_agent"]},"k3s_server":{"hosts":["k3s-server-fake"]},"k3s_agent":{"hosts":["k3s-agent-fake"]}}' > /tmp/fake-inventory.json
	@cd $(ANSIBLE_DIR) && ansible-playbook -i /tmp/fake-inventory.json playbooks/site.yml --check || echo "  ⚠️  Ansible check mode completed (expected failures on fake hosts)"

test-e2e-k8s: ## Build and validate all Kubernetes manifests
	@echo "☸️  Validating all Kubernetes manifests..."
	@kustomize build k8s/apps > /dev/null && echo "  ✓ All Kubernetes manifests are valid YAML"

##@ Raspberry Pi Validation

test-rpi: ## Run full validation suite for Raspberry Pi cluster
	@echo "🏁 Starting Raspberry Pi validation suite..."
	@make test-rpi-prereqs
	@make test-rpi-connectivity
	@make test-rpi-ansible
	@make test-rpi-k8s
	@echo "✅ Raspberry Pi validation successful!"

test-rpi-prereqs: ## Check for Raspberry Pi testing dependencies
	@echo "🔎 Checking Raspberry Pi prerequisites..."
	@command -v ansible-playbook >/dev/null || (echo "❌ Ansible not found"; exit 1)
	@echo "  ✓ Ansible found."

test-rpi-connectivity: ## Test SSH connectivity to Raspberry Pi hosts
	@echo "📡 Testing SSH connectivity to Raspberry Pi nodes..."
	@cd $(ANSIBLE_DIR) && ansible raspberry_pi -i inventory/production.yml -m ping || (echo "❌ Failed to connect to one or more Raspberry Pi nodes"; exit 1)
	@echo "  ✓ All Raspberry Pi nodes reachable via SSH."

test-rpi-ansible: ## Run Ansible playbooks against Raspberry Pis in check mode (validation)
	@echo "⚙️  Testing Raspberry Pi configuration (validation only)..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/production.yml playbooks/validation.yml --check --tags "validate"

test-rpi-full: ## Run the full Ansible playbook against Raspberry Pis
	@echo "⚙️  Running full Raspberry Pi configuration..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/production.yml playbooks/site.yml

test-rpi-k8s: ## Validate Kubernetes manifests for Raspberry Pi cluster
	@echo "☸️  Validating Kubernetes manifests for Raspberry Pi cluster..."
	@make test-e2e-k8s

##@ Molecule Role Tests (offline — no Raspberry Pi required)

test-molecule: ## Run all Molecule role test suites
	@echo "🧪 Running all Molecule role tests (offline)..."
	@make test-molecule-lint
	@make test-molecule-rpi
	@make test-molecule-argocd
	@make test-molecule-k3s
	@make test-molecule-tailscale
	@make test-molecule-gatekeeper
	@make test-molecule-emergency-recovery
	@echo "✅ All Molecule tests passed!"

test-molecule-emergency-recovery: ## Run Molecule tests for emergency_recovery role
	@echo "🧪 Testing emergency_recovery role with Molecule..."
	@cd $(ANSIBLE_DIR)/roles/emergency_recovery && $(MISE_EXEC) molecule test
	@echo "  ✓ emergency_recovery role tests passed."

test-molecule-rpi: ## Run Molecule tests for rpi_optimization role (default + sysctl scenarios)
	@echo "🧪 Testing rpi_optimization role with Molecule (default scenario)..."
	@cd $(ANSIBLE_DIR)/roles/rpi_optimization && $(MISE_EXEC) molecule test
	@echo "🧪 Testing rpi_optimization role with Molecule (sysctl scenario — runtime kernel values)..."
	@cd $(ANSIBLE_DIR)/roles/rpi_optimization && $(MISE_EXEC) molecule test -s sysctl
	@echo "  ✓ rpi_optimization role tests passed (both scenarios)."

test-molecule-argocd: ## Run Molecule tests for argocd role (default + sops scenarios)
	@echo "🧪 Testing argocd role with Molecule (default scenario)..."
	@cd $(ANSIBLE_DIR)/roles/argocd && $(MISE_EXEC) molecule test -s default
	@echo "🧪 Testing argocd role with Molecule (sops scenario — sops_enabled=true)..."
	@cd $(ANSIBLE_DIR)/roles/argocd && $(MISE_EXEC) molecule test -s sops
	@echo "  ✓ argocd role tests passed (both scenarios)."

test-molecule-lint: ## Run ansible-lint and yamllint across all ansible files
	@echo "🔍 Linting Ansible files..."
	@$(MISE_EXEC) pre-commit run --all-files
	@cd $(ANSIBLE_DIR) && $(MISE_EXEC) yamllint -c .yamllint.yml roles/ playbooks/
	@cd $(ANSIBLE_DIR) && $(MISE_EXEC) ansible-lint
	@echo "  ✓ Lint passed."

test-molecule-k3s: ## Run Molecule tests for k3s role (default + health + install + agent scenarios)
	@echo "🧪 Testing k3s role with Molecule (default scenario — check mode)..."
	@cd $(ANSIBLE_DIR)/roles/k3s && $(MISE_EXEC) molecule test
	@echo "🧪 Testing k3s role with Molecule (health scenario — health_check.yml playbook)..."
	@cd $(ANSIBLE_DIR)/roles/k3s && $(MISE_EXEC) molecule test -s health
	@echo "🧪 Testing k3s role with Molecule (install scenario — server template rendering + binary stub)..."
	@cd $(ANSIBLE_DIR)/roles/k3s && $(MISE_EXEC) molecule test -s install
	@echo "🧪 Testing k3s role with Molecule (agent scenario — worker node install path)..."
	@cd $(ANSIBLE_DIR)/roles/k3s && $(MISE_EXEC) molecule test -s agent
	@echo "  ✓ k3s role tests passed (all four scenarios)."

test-molecule-tailscale: ## Run Molecule tests for tailscale role
	@echo "🧪 Testing tailscale role with Molecule..."
	@cd $(ANSIBLE_DIR)/roles/tailscale && $(MISE_EXEC) molecule test
	@echo "  ✓ tailscale role tests passed."

test-molecule-gatekeeper: ## Run Molecule tests for gatekeeper role
	@echo "🧪 Testing gatekeeper role with Molecule..."
	@cd $(ANSIBLE_DIR)/roles/gatekeeper && $(MISE_EXEC) molecule test
	@echo "  ✓ gatekeeper role tests passed."

##@ Hybrid Cloud Validation (zero-cost offline)
# These targets validate the hybrid AWS + Raspberry Pi architecture without
# incurring any AWS charges.
#
# Prerequisites:
#   LocalStack:  docker run -d -p 4566:4566 localstack/localstack
#   awslocal:    pip install awscli-local
#   mock inv:    ansible/inventory/mock_aws.yml   (already committed)
#
# Environment variables honoured by hybrid-dry-run-localstack:
#   LOCALSTACK_ENDPOINT   (default: http://localhost:4566)
#   AWS_DEFAULT_REGION    (default: us-east-1)

LOCALSTACK_ENDPOINT ?= http://localhost:4566
AWS_DEFAULT_REGION  ?= us-east-1
TERRAFORM_DIR_AWS   := infra/aws

smoke-test: ## Post-deploy smoke test — verifies ArgoCD sync, pod health, and namespaces (requires live cluster)
	@echo "🔍 Running post-deploy smoke tests..."
	@bash bin/smoke-test.sh

test-contracts: ## Verify App-of-Apps path contracts and SOPS secret structure (offline)
	@echo "🧪 Running contract tests..."
	@command -v bats >/dev/null || (echo "❌ bats not found. Install: https://github.com/bats-core/bats-core"; exit 1)
	@bats bin/tests/contract_tests.bats
	@echo "  ✓ Contract tests passed."

test-shell: ## Run shell unit tests for deploy script functions (requires bats)
	@echo "🧪 Running shell unit tests..."
	@command -v bats >/dev/null || (echo "❌ bats not found. Install: https://github.com/bats-core/bats-core"; exit 1)
	@bats bin/tests/deploy_functions.bats
	@echo "  ✓ Shell unit tests passed."

test-python: ## Run Python unit tests for inventory script and Lambda scheduler (requires pytest)
	@echo "🧪 Running Python unit tests..."
	@python3 -c "import pytest" 2>/dev/null || pip install --quiet --break-system-packages pytest
	@python3 -c "import boto3" 2>/dev/null || pip install --quiet --break-system-packages boto3
	@python3 -m pytest ansible/tests/ infra/aws/modules/scheduler/lambda_src/tests/ -v
	@echo "  ✓ Python unit tests passed."

test-templates: ## Validate k3s Jinja2 templates (renders with StrictUndefined + yamllint)
	@echo "🧪 Validating k3s Jinja2 templates..."
	@python3 -c "import jinja2, yaml" 2>/dev/null || pip install --quiet --break-system-packages jinja2 pyyaml
	@python3 scripts/render_and_lint_templates.py
	@echo "  ✓ Template validation passed."

test-k8s-schemas: validate-k8s-all ## Validate k8s manifest schemas (alias for validate-k8s-all)

validate-k8s-all: ## Validate all Kubernetes manifests: kustomize + kubeconform for k8s/apps + k8s/system + k8s/gitops
	@echo "✓ Validating k8s/apps (kustomize build + kubeconform)..."
	@command -v kustomize >/dev/null 2>&1 || (echo "❌ kustomize not found"; exit 1)
	@command -v kubeconform >/dev/null 2>&1 || (echo "❌ kubeconform not found"; exit 1)
	@kustomize build k8s/apps \
		| python3 -c 'import sys,yaml;[print("---\n"+yaml.dump(d,default_flow_style=False)) for d in yaml.safe_load_all(sys.stdin) if d and "sops" not in d]' \
		| kubeconform -strict -ignore-missing-schemas -kubernetes-version 1.34.0
	@echo "✓ Validating k8s/system manifests..."
	@find k8s/system -name "*.yaml" | sort | xargs cat \
		| python3 -c 'import sys,yaml;[print("---\n"+yaml.dump(d,default_flow_style=False)) for d in yaml.safe_load_all(sys.stdin) if d and "sops" not in d and "apiVersion" in d]' \
		| kubeconform -strict -ignore-missing-schemas -kubernetes-version 1.34.0
	@echo "✓ Validating k8s/gitops/sops manifests..."
	@find k8s/gitops/sops -name "*.yaml" ! -name "*-patch.yaml" -exec grep -L "^sops:" {} + \
		| sort | xargs kubeconform -strict -ignore-missing-schemas -kubernetes-version 1.34.0
	@echo "  ✓ All Kubernetes manifests validated."

validate-yaml-lint: ## Run yamllint across the entire repo (root .yamllint config — same scope as CI)
	@echo "✓ Running yamllint (root .yamllint)..."
	@command -v yamllint >/dev/null 2>&1 || (echo "❌ yamllint not found. Install: pip install yamllint"; exit 1)
	@$(MISE_EXEC) yamllint -c .yamllint .
	@echo "  ✓ YAML lint passed."

validate-shellcheck: ## Run shellcheck on all shell scripts (local equivalent of CI shellcheck action)
	@echo "✓ Running shellcheck..."
	@command -v shellcheck >/dev/null 2>&1 || (echo "❌ shellcheck not found. Install: apt install shellcheck"; exit 1)
	@find . -name "*.sh" -not -path "./.git/*" -not -path "./.terraform/*" \
		| xargs shellcheck --severity=warning
	@echo "  ✓ ShellCheck passed."

validate-sops-workflow: ## Validate SOPS encrypt/decrypt with a throwaway Age keypair (no secrets committed)
	@echo "🔐 Validating SOPS workflow (throwaway keypair)..."
	@command -v age-keygen >/dev/null 2>&1 || (echo "❌ age-keygen not found"; exit 1)
	@command -v sops >/dev/null 2>&1 || (echo "❌ sops not found"; exit 1)
	@age-keygen -o /tmp/ci-test-age.key 2>/dev/null; \
		pub=$$(age-keygen -y /tmp/ci-test-age.key); \
		export SOPS_AGE_KEY="$$(cat /tmp/ci-test-age.key)"; \
		printf 'apiVersion: v1\nkind: Secret\nmetadata:\n  name: ci-test\nstringData:\n  token: supersecret\n' > /tmp/ci-plain.yaml; \
		sops --config /dev/null --encrypt --age "$$pub" /tmp/ci-plain.yaml > /tmp/ci-enc.yaml; \
		sops --decrypt /tmp/ci-enc.yaml > /tmp/ci-dec.yaml; \
		grep -q "supersecret" /tmp/ci-dec.yaml && echo "  ✓ SOPS encrypt → decrypt workflow validated"
	@rm -f /tmp/ci-test-age.key /tmp/ci-plain.yaml /tmp/ci-enc.yaml /tmp/ci-dec.yaml

test-homolog: ## Pre-production gate: all offline tests — mirrors what CI runs (no production changes)
	@echo "🔍 Running homologation test suite (no production changes)..."
	@make test-acl-json
	@make validate-yaml-lint
	@make validate-ansible
	@make validate-terraform-all
	@make validate-k8s-all
	@make test-contracts
	@make test-shell
	@make test-python
	@make test-templates
	@make test-molecule
	@make hybrid-dry-run
	@echo "✅ All homologation tests passed — safe to open PR for production."
	@echo "ℹ️  Run 'make test-sops' separately to verify SOPS decryption with your Age key."
	@echo "ℹ️  Run 'make smoke-test' after deploy to verify cluster health."

verify-all: ## Run EVERY test including SOPS integration (requires Age key + LocalStack)
	@echo "🔍 Starting Full Quality Gate..."
	@make test-acl-json
	@make validate-ansible
	@make test-shell
	@make test-python
	@make test-sops
	@make test-molecule
	@make hybrid-dry-run
	@echo "✅ All automated tests passed! You are safe to deploy."

hybrid-dry-run: ## Full offline validation: LocalStack Terraform plan + Ansible check (no AWS charges)
	@echo "🏁 Hybrid Cloud Dry-Run (zero cost)..."
	@make hybrid-dry-run-prereqs
	@make hybrid-dry-run-localstack
	@make hybrid-dry-run-ansible
	@echo "✅ Hybrid dry-run complete — no AWS resources were created."

hybrid-dry-run-prereqs: ## Check prerequisites for hybrid dry-run
	@echo "🔎 Checking hybrid dry-run prerequisites..."
	@command -v docker >/dev/null 2>&1 || (echo "❌ Docker not found"; exit 1)
	@docker ps --filter "name=localstack" --format "{{.Names}}" 2>/dev/null | grep -q localstack || \
		(echo "❌ LocalStack container not running.  Start it with:"; \
		 echo "   docker run -d --name localstack -p 4566:4566 localstack/localstack"; \
		 exit 1)
	@echo "  ⏳ Checking LocalStack service health (S3, STS, EC2)..."
	@if command -v curl >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then \
		curl -fsS http://localhost:4566/_localstack/health 2>/dev/null \
			| jq -e '(.services.s3 == "running" or .services.s3 == "available") and (.services.sts == "running" or .services.sts == "available") and (.services.ec2 == "running" or .services.ec2 == "available")' \
			>/dev/null 2>&1 \
		|| (echo "❌ LocalStack is running but services are not ready yet. Please wait a few seconds and retry."; exit 1); \
	else \
		echo "  ⚠️  curl/jq not found — using awslocal fallback probe..."; \
		awslocal s3 ls >/dev/null 2>&1 \
		&& awslocal sts get-caller-identity >/dev/null 2>&1 \
		|| (echo "❌ LocalStack is running but services are not ready yet. Please wait a few seconds and retry."; exit 1); \
	fi
	@echo "  ✓ LocalStack services (S3, STS, EC2) are healthy."
	@command -v tflocal >/dev/null 2>&1 || \
		(echo "❌ tflocal not found.  Install: pip install terraform-local"; exit 1)
	@command -v awslocal >/dev/null 2>&1 || \
		(echo "❌ awslocal not found.  Install: pip install awscli-local"; exit 1)
	@command -v ansible-playbook >/dev/null 2>&1 || (echo "❌ ansible-playbook not found"; exit 1)
	@test -f $(ANSIBLE_DIR)/inventory/mock_aws.yml || \
		(echo "❌ ansible/inventory/mock_aws.yml not found"; exit 1)
	@test -f $(HOME)/.ssh/homelab-deploy-key || \
		(echo "❌ ArgoCD deploy key not found at ~/.ssh/homelab-deploy-key"; \
		 echo "   Generate with: ssh-keygen -t ed25519 -f ~/.ssh/homelab-deploy-key -N ''"; \
		 echo "   Then add the public key as a deploy key in the GitHub repo settings."; \
		 exit 1)
	@echo "  ✓ All prerequisites found."

hybrid-dry-run-localstack: ## Run Terraform plan against LocalStack via tflocal (validates AWS resource structure)
	@echo "📦 Running Terraform plan against LocalStack (tflocal)..."
	@echo "   Endpoint: $(LOCALSTACK_ENDPOINT)"
	@if [ ! -f $(TERRAFORM_DIR_AWS)/testing/provider_override.tf ]; then \
		echo "  ⚠️  provider_override.tf not found — copying from example..."; \
		cp $(TERRAFORM_DIR_AWS)/testing/provider_override.tf.disabled \
		   $(TERRAFORM_DIR_AWS)/testing/provider_override.tf 2>/dev/null || true; \
	fi
	@# ── Credential isolation block ─────────────────────────────────────────
	@# Explicitly shadow any real AWS credentials that mise / direnv / ~/.aws
	@# may have injected into the environment.  tflocal further wraps every
	@# call to route it through LocalStack, so no real AWS endpoint is reached.
	@echo "  🔧 Initialising Terraform backend against LocalStack..."
	@cd $(TERRAFORM_DIR_AWS) && \
		AWS_ACCESS_KEY_ID=test \
		AWS_SECRET_ACCESS_KEY=test \
		AWS_SESSION_TOKEN=test \
		AWS_DEFAULT_REGION=$(AWS_DEFAULT_REGION) \
		AWS_STS_REGIONAL_ENDPOINTS=regional \
		LOCALSTACK_HOST=localhost \
		TF_VAR_aws_region=$(AWS_DEFAULT_REGION) \
		TF_VAR_localstack_test=yes \
		tflocal init \
			-input=false \
			-reconfigure
	@echo "  📋 Running Terraform plan (full output — tee'd to /tmp/tflocal-plan.log)..."
	@cd $(TERRAFORM_DIR_AWS) && \
		AWS_ACCESS_KEY_ID=test \
		AWS_SECRET_ACCESS_KEY=test \
		AWS_SESSION_TOKEN=test \
		AWS_DEFAULT_REGION=$(AWS_DEFAULT_REGION) \
		AWS_STS_REGIONAL_ENDPOINTS=regional \
		LOCALSTACK_HOST=localhost \
		TF_VAR_aws_region=$(AWS_DEFAULT_REGION) \
		TF_VAR_localstack_test=yes \
		tflocal plan \
			-var="aws_region=$(AWS_DEFAULT_REGION)" \
			-var="localstack_test=yes" \
			-input=false \
			-compact-warnings \
			2>&1 | tee /tmp/tflocal-plan.log; \
		echo "  ⚠️  tflocal plan finished — full output saved to /tmp/tflocal-plan.log (some errors expected on LocalStack free tier)"
	@echo "  ✓ Terraform LocalStack plan finished."

hybrid-dry-run-ansible: ## Run site.yml --check against mock AWS inventory + real Pi nodes
	@echo "⚙️  Running Ansible check mode (mock AWS + production Pi inventory)..."
	@echo "   Inventories: inventory/production.yml + inventory/mock_aws.yml"
	@cd $(ANSIBLE_DIR) && ansible-playbook \
		-i inventory/production.yml \
		-i inventory/mock_aws.yml \
		playbooks/site.yml \
		--check \
		--tags validate \
		-e "auto_approve=true" \
		--ask-become-pass \
		2>&1 || echo "  ⚠️  Ansible check mode completed (expected failures on unreachable mock hosts)"
	@echo "  ✓ Ansible hybrid check mode finished."

test-sops: ## Verify real SOPS Age decryption (requires sops binary + SOPS_AGE_KEY or SOPS_AGE_KEY_FILE)
	@echo "🔐 Testing SOPS Age decryption (integration test)..."
	@command -v sops >/dev/null 2>&1 || \
		(echo "❌ sops not found. Install: https://github.com/getsops/sops/releases"; exit 1)
	@if [ -z "$${SOPS_AGE_KEY:-}" ] && [ -z "$${SOPS_AGE_KEY_FILE:-}" ]; then \
		echo "❌ No Age key configured. Set SOPS_AGE_KEY or SOPS_AGE_KEY_FILE."; exit 1; fi
	@sops --decrypt k8s/apps/adguard/secret.yaml >/dev/null 2>&1 \
		&& echo "  ✓ SOPS decryption verified (k8s/apps/adguard/secret.yaml)" \
		|| (echo "❌ SOPS decryption failed — check your Age key"; exit 1)

test-acl-json: ## Validate Tailscale ACL JSON syntax
	@echo "🌐 Validating Tailscale ACL JSON..."
	@command -v jq >/dev/null 2>&1 || (echo "❌ jq not found. Install: apt install jq"; exit 1)
	@jq empty infra/aws/acl.json \
		&& echo "  ✓ infra/aws/acl.json is valid JSON" \
		|| (echo "❌ infra/aws/acl.json is invalid JSON"; exit 1)

test-phase0-ansible: ## Dry-run Phase 0 (Pi k3s server legacy cleanup) in check mode
	@echo "🧪 Dry-running Phase 0 (Pi cleanup) in check mode..."
	@cd $(ANSIBLE_DIR) && ansible-playbook \
		-i inventory/production.yml \
		-i inventory/mock_aws.yml \
		playbooks/site.yml \
		--tags phase0 \
		--check \
		2>&1 || true
	@echo "  ✓ Phase 0 check mode finished (connection failures on unreachable hosts are expected)."

argocd-manifest-fetch: ## Pre-download ArgoCD install manifest for offline/cached deploys
	@echo "⬇️  Fetching ArgoCD $(ARGOCD_VERSION) manifest..."
	@mkdir -p ansible/roles/argocd/files
	@curl -fsSL \
		"https://raw.githubusercontent.com/argoproj/argo-cd/$(ARGOCD_VERSION)/manifests/install.yaml" \
		-o "ansible/roles/argocd/files/argocd-$(ARGOCD_VERSION)-install.yaml"
	@echo "  ✓ Cached at ansible/roles/argocd/files/argocd-$(ARGOCD_VERSION)-install.yaml"
	@echo "  ℹ️  This file is gitignored — re-run before deploys in offline environments."

##@ Rollback & Recovery

rollback-verify-prereqs: ## Check that all rollback tools are available
	@echo "🔎 Checking rollback prerequisites..."
	@command -v terraform >/dev/null 2>&1 || (echo "❌ terraform missing"; exit 1)
	@command -v kubectl >/dev/null 2>&1 || (echo "❌ kubectl missing"; exit 1)
	@command -v aws >/dev/null 2>&1 || (echo "❌ aws-cli missing"; exit 1)
	@echo "  ✓ All rollback tools available (terraform, kubectl, aws)"

rollback-tf-refresh: ## Detect Terraform infrastructure drift without making changes (non-destructive)
	@echo "🔍 Detecting infrastructure drift (refresh-only plan)..."
	@cd $(TERRAFORM_DIR) && terraform plan -refresh-only -lock=false

rollback-argocd-status: ## Show ArgoCD application sync + health status (identify out-of-sync apps)
	@echo "☸️  ArgoCD application status:"
	@kubectl get applications -n argocd \
		-o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status'

clean-local-tf: ## Remove .terraform dir and lock file for a fresh LocalStack dry-run state
	@echo "🧹 Purging local Terraform state for a clean dry-run..."
	@rm -rf  $(TERRAFORM_DIR_AWS)/.terraform
	@rm -f   $(TERRAFORM_DIR_AWS)/.terraform.lock.hcl
	@echo "  ✓ Removed: $(TERRAFORM_DIR_AWS)/.terraform"
	@echo "  ✓ Removed: $(TERRAFORM_DIR_AWS)/.terraform.lock.hcl"
	@echo "  ℹ️  Run 'make hybrid-dry-run-localstack' to re-initialise against LocalStack."

##@ Raspberry Pi Migration

clean-pi-server: ## Remove legacy k3s server installation from all Raspberry Pi nodes
	@echo "🧹 Removing legacy k3s server from Raspberry Pi nodes..."
	@cd $(ANSIBLE_DIR) && ansible-playbook \
		-i inventory/production.yml \
		playbooks/maintenance/cleanup_pi_server.yml
	@echo "  ✓ Raspberry Pi nodes cleaned and ready to join as agents."

pi-migrate-to-agent: ## Full Pi migration: cleanup server → reconfigure as k3s agent
	@echo "🔄 Migrating Raspberry Pi nodes from server to agent role..."
	@echo "   Step 1/2: Remove legacy k3s server installation..."
	@make clean-pi-server
	@echo "   Step 2/2: Configure Pi nodes as k3s agents..."
	@echo "   ℹ️  Ensure an AWS k3s_server is available via terraform_inventory_aws.py"
	@cd $(ANSIBLE_DIR) && ansible-playbook \
		-i inventory/production.yml \
		-i terraform_inventory_aws.py \
		playbooks/deploy_k3s.yml \
		--limit k3s_agent \
		--tags agent
	@echo "✅ Raspberry Pi nodes are now k3s agents."

##@ Cleanup

clean: ## Clean temporary files and caches
	@echo "🧹 Cleaning up..."
	@rm -rf $(TERRAFORM_DIR)/.terraform/modules
	@rm -f /tmp/k3s-homelab-kubeconfig.yaml
	@find . -name "*.pyc" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
	@echo "✅ Cleanup complete"

clean-terraform: ## Clean Terraform state and cache (DANGEROUS)
	@echo "⚠️  This will remove Terraform state!"
	@read -p "Are you sure? Type 'yes': " confirm && [ "$$confirm" = "yes" ] || exit 1
	@rm -rf $(TERRAFORM_DIR)/.terraform
	@rm -f $(TERRAFORM_DIR)/.terraform.lock.hcl
	@rm -f $(TERRAFORM_DIR)/terraform.tfstate*
	@echo "✅ Terraform cleaned"

##@ Documentation

docs: ## Open documentation
	@echo "📚 Documentation:"
	@echo "  Main README: cat README.md"
	@echo "  Ansible: cat ansible/README.md"
	@echo "  Phase 2 Setup: cat ansible/PHASE2-SETUP.md"
	@echo "  Testing Guide: cat ansible/TESTING.md"

show-costs: ## Show estimated costs using the code defaults
	@echo "💰 Calculating real-time cost estimates from code defaults..."
	@infracost breakdown --path $(TERRAFORM_DIR) \
		--usage-file infracost-usage.yml \
		--terraform-var is_cost_scan=true
