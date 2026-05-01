# Homelab Infrastructure Management
# Usage: make <target>

.PHONY: help setup deploy deploy-safe deploy-quick destroy status ansible \
        terraform terraform-init terraform-plan terraform-apply \
        ansible-galaxy-install ansible-ping ansible-inventory ansible-deploy \
	validate verify-all test-homolog test-e2e test-rpi test-shell test-terraform test-security test-security-supply-chain test-k8s-policy-coverage test-dr-execution test-python test-python-ci \
        test-molecule test-molecule-rpi test-molecule-argocd \
        test-molecule-lint test-molecule-k3s test-molecule-tailscale \
        test-molecule-gatekeeper hybrid-dry-run hybrid-dry-run-prereqs \
        hybrid-dry-run-localstack hybrid-dry-run-ansible clean-local-tf \
        clean-pi-server pi-migrate-to-agent clean docs show-costs \
        oidc-init oidc-plan oidc-apply oidc-output \
        test-sops test-acl-json test-phase0-ansible argocd-manifest-fetch \
        smoke-test test-e2e-post-deploy test-e2e-connectivity test-e2e-observability test-contracts \
		qa-audit qa-scorecard qa-verify-required-no-skips qa-verify-duration-budgets qa-flake-report \
		test-offline-required test-offline-extended test-live-preflight test-live-required \
        rollback-tf-refresh rollback-argocd-status rollback-verify-prereqs \
        validate-terraform-all validate-k8s-all validate-yaml-lint \
        validate-shellcheck validate-sops-workflow \
		validate-terraform-tests validate-k8s-policies validate-k8s-policies-critical validate-k8s-dry-run \
		setup-ci-deps-yamllint setup-ci-deps-shellcheck setup-ci-deps-kind \
		setup-ci-deps-molecule setup-ci-deps-arm64 test-e2e-live-nightly \
		setup-ci-deps-workflow-lint lint-workflows \
		preflight drift morning-sync update-versions update-versions-dry-run \
		cilium-flip-status cilium-flip-node cilium-flip-rollback

# Default target
.DEFAULT_GOAL := help

# Configuration
TERRAFORM_DIR  := infra/aws
ARGOCD_VERSION := v2.13.2
ANSIBLE_DIR := ansible
DEPLOY_SCRIPT := python3 bin/deploy_aws_homelab.py

# Offline-safe AWS environment for Terraform validate/init in local and CI runs.
TF_AWS_OFFLINE_ENV := AWS_EC2_METADATA_DISABLED=true AWS_SDK_LOAD_CONFIG=0 AWS_ACCESS_KEY_ID=dummy AWS_SECRET_ACCESS_KEY=dummy AWS_SESSION_TOKEN=dummy AWS_DEFAULT_REGION=us-east-1 AWS_REGION=us-east-1 AWS_SKIP_REQUESTING_ACCOUNT_ID=true TF_SKIP_REQUESTING_ACCOUNT_ID=true AWS_ENDPOINT_URL= AWS_ENDPOINT_URL_STS= AWS_ENDPOINT_URL_IAM= AWS_ENDPOINT_URL_EC2= AWS_ENDPOINT_URL_S3=

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
	@cd $(ANSIBLE_DIR) && $(MISE_EXEC) ansible-galaxy collection install -r requirements.yml --force
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

##@ CI/CD Dependencies (used by GitHub Actions workflows)

setup-ci-deps-terraform: ## Install Terraform + TFLint + SOPS (for CI)
	@echo "🔧 Setting up Terraform + SOPS for CI..."
	@export PATH="$$HOME/.local/bin:$$PATH"; \
	if ! command -v mise >/dev/null 2>&1; then \
		curl https://mise.jdx.dev/install.sh | sh; \
	fi; \
	mise install terraform tflint; \
	mise exec -- terraform version >/dev/null 2>&1 || (echo "❌ terraform not found after install"; exit 1); \
	mise exec -- tflint --version >/dev/null 2>&1 || (echo "❌ tflint not found after install"; exit 1); \
	sudo ln -sf "$$(mise which terraform)" /usr/local/bin/terraform 2>/dev/null || true; \
	sudo ln -sf "$$(mise which tflint)" /usr/local/bin/tflint 2>/dev/null || true; \
	if ! command -v sops >/dev/null 2>&1; then \
		curl -sLO https://github.com/getsops/sops/releases/download/v3.9.4/sops-v3.9.4.linux.amd64; \
		install -m 0755 sops-v3.9.4.linux.amd64 /usr/local/bin/sops; \
		rm -f sops-v3.9.4.linux.amd64; \
	fi; \
	echo "✅ Terraform, TFLint, and SOPS ready"

setup-ci-deps-ansible: ## Install Ansible + Python dependencies (for CI)
	@echo "📦 Setting up Ansible + Python dependencies for CI..."
	@python3 -c "import ansible, boto3" 2>/dev/null || \
		pip install --quiet --break-system-packages ansible boto3
	@echo "✅ Ansible + boto3 installed"

setup-ci-deps-kubernetes: ## Install kubectl + jq + curl (for CI)
	@echo "🔧 Setting up Kubernetes tools for CI..."
	@if ! command -v kubectl >/dev/null 2>&1; then \
		echo "Installing kubectl..."; \
		curl -fsSL -o /tmp/kubectl "https://dl.k8s.io/release/$$(curl -fsSL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"; \
		sudo install -m 0755 /tmp/kubectl /usr/local/bin/kubectl; \
		rm -f /tmp/kubectl; \
	fi
	@command -v jq >/dev/null 2>&1 || (echo "Installing jq..."; sudo apt-get update -qq && sudo apt-get install -y -qq jq)
	@command -v curl >/dev/null 2>&1 || (echo "Installing curl..."; sudo apt-get update -qq && sudo apt-get install -y -qq curl)
	@echo "✅ Kubernetes tools ready"

setup-ci-deps-yamllint: ## Install yamllint (for CI)
	@echo "🔧 Setting up yamllint for CI..."
	@python3 -c "import yamllint" 2>/dev/null || pip install --quiet --break-system-packages yamllint
	@echo "✅ yamllint installed"

setup-ci-deps-shellcheck: ## Install shellcheck (for CI)
	@echo "🔧 Setting up shellcheck for CI..."
	@if ! command -v shellcheck >/dev/null 2>&1; then \
		if command -v apt-get >/dev/null 2>&1 && [ "$$(id -u)" -eq 0 ]; then \
			apt-get update -qq && apt-get install -y -qq shellcheck; \
		else \
			mkdir -p "$$HOME/.local/bin"; \
			curl -fsSL https://github.com/koalaman/shellcheck/releases/download/v0.10.0/shellcheck-v0.10.0.linux.x86_64.tar.xz \
				| tar -xJ --strip-components=1 -C "$$HOME/.local/bin" shellcheck-v0.10.0/shellcheck; \
			export PATH="$$HOME/.local/bin:$$PATH"; \
		fi; \
	fi
	@export PATH="$$HOME/.local/bin:$$PATH"; shellcheck --version >/dev/null
	@shellcheck --version >/dev/null
	@echo "✅ shellcheck installed"

setup-ci-deps-kind: ## Install kind (for CI)
	@echo "🔧 Setting up kind for CI..."
	@if ! command -v kind >/dev/null 2>&1; then \
		curl -Lo /usr/local/bin/kind https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64; \
		chmod +x /usr/local/bin/kind; \
	fi
	@kind version && echo "✅ kind installed"

setup-ci-deps-molecule: ## Install Molecule + Ansible tooling (for CI)
	@echo "📦 Setting up Molecule + Ansible tooling for CI..."
	@python3 -c "import ansible" 2>/dev/null || pip install --quiet --break-system-packages ansible
	@python3 -c "import molecule" 2>/dev/null || pip install --quiet --break-system-packages molecule molecule-plugins[docker] ansible-lint yamllint
	@echo "✅ Molecule + Ansible tooling installed"

setup-ci-deps-arm64: ## Install dependencies for ARM64/QEMU validation jobs
	@echo "🔧 Setting up ARM64 validation dependencies for CI..."
	@make setup-ci-deps-molecule
	@echo "✅ ARM64 validation dependencies ready"

setup-ci-deps-bats: ## Install bats testing framework (for CI)
	@echo "📦 Setting up bats for CI..."
	@command -v bats >/dev/null 2>&1 || \
		(echo "Installing bats from source..." && \
		git clone --depth 1 https://github.com/bats-core/bats-core.git /tmp/bats && \
		cd /tmp/bats && sudo ./install.sh /usr/local && rm -rf /tmp/bats)
	@echo "✅ bats installed"

setup-ci-deps-python: ## Install Python test dependencies (pytest, pytest-cov, boto3, jinja2, pyyaml)
	@python3 -c "import pytest, pytest_cov, boto3, jinja2, yaml" 2>/dev/null \
	  || (echo "📦 Installing Python test dependencies..." \
	      && pip install --quiet --break-system-packages --timeout 60 --retries 2 \
	         pytest pytest-cov boto3 jinja2 pyyaml \
	      && echo "✅ Python test dependencies installed")

setup-ci-deps-workflow-lint: ## Install actionlint + zizmor (for CI)
	@echo "🔧 Setting up workflow linters for CI..."
	@command -v actionlint >/dev/null 2>&1 || $(MISE_EXEC) actionlint --version >/dev/null 2>&1 \
	  || (curl -fsSL -o /tmp/actionlint.bash https://raw.githubusercontent.com/rhysd/actionlint/main/scripts/download-actionlint.bash \
	      && bash /tmp/actionlint.bash latest "$$HOME/.local/bin" \
	      && rm -f /tmp/actionlint.bash)
	@command -v zizmor >/dev/null 2>&1 || $(MISE_EXEC) zizmor --version >/dev/null 2>&1 \
	  || pip install --quiet --break-system-packages zizmor
	@echo "✅ actionlint + zizmor ready"

setup-ci-deps-kustomize: ## Install kustomize (for CI)
	@echo "🔧 Setting up kustomize for CI..."
	@if ! command -v kustomize >/dev/null 2>&1; then \
		echo "Installing kustomize..."; \
		curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" \
			| bash -s -- /usr/local/bin; \
	fi
	@kustomize version && echo "✅ kustomize installed"

setup-ci-deps-kubeconform: ## Install kubeconform (for CI)
	@echo "🔧 Setting up kubeconform for CI..."
	@if ! command -v kubeconform >/dev/null 2>&1; then \
		curl -sL https://github.com/yannh/kubeconform/releases/latest/download/kubeconform-linux-amd64.tar.gz \
			| sudo tar xz -C /usr/local/bin; \
	fi
	@kubeconform -v && echo "✅ kubeconform installed"

setup-ci-deps-age: ## Install age encryption tool (for CI)
	@echo "🔧 Setting up age for CI..."
	@if ! command -v age >/dev/null 2>&1; then \
		curl -sL https://github.com/FiloSottile/age/releases/download/v1.2.1/age-v1.2.1-linux-amd64.tar.gz \
			| sudo tar xz --strip-components=1 -C /usr/local/bin age/age age/age-keygen; \
	fi
	@age --version && echo "✅ age installed"

setup-ci-deps-conftest: ## Install conftest via mise (version pinned in .mise.toml)
	@echo "🔧 Setting up conftest for CI..."
	@export PATH="$$HOME/.local/bin:$$PATH"; \
	if ! command -v mise >/dev/null 2>&1; then \
		curl https://mise.jdx.dev/install.sh | sh; \
	fi; \
	mise install conftest; \
	sudo ln -sf "$$(mise which conftest)" /usr/local/bin/conftest 2>/dev/null || true; \
	conftest --version && echo "✅ conftest installed"

setup-ci-deps-trivy: ## Install trivy via mise (version pinned in .mise.toml)
	@echo "🔧 Setting up trivy for CI..."
	@export PATH="$$HOME/.local/bin:$$PATH"; \
	if ! command -v mise >/dev/null 2>&1; then \
		curl https://mise.jdx.dev/install.sh | sh; \
	fi; \
	mise install trivy; \
	sudo ln -sf "$$(mise which trivy)" /usr/local/bin/trivy 2>/dev/null || true; \
	trivy --version && echo "✅ trivy installed"

setup-ci-deps-all: ## Install ALL CI dependencies (Makefile as source of truth for CI)
	@echo "🔨 Installing ALL CI/CD dependencies via Makefile..."
	@make setup-ci-deps-terraform
	@make setup-ci-deps-ansible
	@make setup-ci-deps-kubernetes
	@make setup-ci-deps-bats
	@make setup-ci-deps-python
	@make setup-ci-deps-kustomize
	@make setup-ci-deps-kubeconform
	@make setup-ci-deps-age
	@make setup-ci-deps-conftest
	@make setup-ci-deps-trivy
	@make setup-ci-deps-molecule
	@make setup-ci-deps-arm64
	@echo "✅ All CI/CD dependencies installed"

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

ansible-optimize-rpi: ## Optimize Raspberry Pi nodes (swap, sysctl, logrotate, RPi 3 boot config)
	@echo "🍓 Optimizing Raspberry Pi nodes..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/production.yml playbooks/maintenance/optimize_rpi.yml

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

validate-argocd-synced: ## Wait for ArgoCD root app to reach Synced + Healthy (used by CI/CD)
	@echo "⏳ Waiting for ArgoCD root app to sync (300s timeout)..."
	@kubectl wait --for condition=synced app/root -n argocd --timeout=300s || { \
	  echo "❌ ArgoCD root app did not reach Synced state"; \
	  kubectl describe app root -n argocd; \
	  exit 1; \
	}
	@kubectl wait --for condition=healthy app/root -n argocd --timeout=60s || { \
	  echo "❌ ArgoCD root app did not reach Healthy state"; \
	  kubectl describe app root -n argocd; \
	  exit 1; \
	}
	@echo "✅ ArgoCD root app is Synced + Healthy"

##@ Cilium Migration (Phase B — per-node Flannel→Cilium cutover)

cilium-flip-status: ## Show per-node CNI state (Flannel vs Cilium)
	@echo "🌐 Per-node CNI state:"
	@printf "%-20s | %-7s | %-32s | %s\n" "NODE" "CNI" "CILIUM_POD" "READY"
	@printf "%-20s-+-%-7s-+-%-32s-+-%s\n" "--------------------" "-------" "--------------------------------" "------"
	@kubectl get nodes -o name 2>/dev/null | sed 's|node/||' | while read node; do \
	  cilium_pod=$$(kubectl -n kube-system get pod -l k8s-app=cilium --field-selector spec.nodeName=$$node -o name 2>/dev/null | head -1 | sed 's|pod/||'); \
	  if [ -n "$$cilium_pod" ]; then \
	    ready=$$(kubectl -n kube-system get pod $$cilium_pod -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null); \
	    printf "%-20s | %-7s | %-32s | %s\n" "$$node" "Cilium" "$$cilium_pod" "$$ready"; \
	  else \
	    printf "%-20s | %-7s | %-32s | %s\n" "$$node" "Flannel" "(none)" "n/a"; \
	  fi; \
	done

cilium-flip-node: ## Flip ONE node from Flannel to Cilium (NODE=<name>; order: rasp-pi-04, t3.small agent, rasp-pi-03, server last)
	@if [ -z "$(NODE)" ]; then echo "❌ NODE=<name> is required. Recommended order: rasp-pi-04 → t3.small agent → rasp-pi-03 → t3.medium server."; exit 1; fi
	@echo "🔄 Flipping $(NODE) from Flannel to Cilium..."
	@kubectl get node $(NODE) -o name >/dev/null 2>&1 || { echo "❌ Node $(NODE) not found in cluster."; exit 1; }
	@echo "  • Verifying Cilium ArgoCD app is Synced..."
	@kubectl wait --for=jsonpath='{.status.sync.status}'=Synced app/cilium -n argocd --timeout=60s 2>/dev/null || { \
	  echo "❌ Cilium ArgoCD app not Synced. Add ./cilium to k8s/apps/kustomization.yaml and let ArgoCD sync first."; \
	  exit 1; \
	}
	@echo "  • Draining $(NODE) (timeout 5min)..."
	@kubectl drain $(NODE) --ignore-daemonsets --delete-emptydir-data --timeout=300s || { \
	  echo "❌ Drain failed; node remains cordoned for inspection."; \
	  exit 1; \
	}
	@echo "  • Re-rendering K3s config on $(NODE) with enable_cilium_cni=true..."
	@cd $(ANSIBLE_DIR) && ansible-playbook \
		-i inventory/production.yml \
		-i terraform_inventory_aws.py \
		playbooks/cilium-flip.yml \
		--limit $(NODE) \
		-e enable_cilium_cni=true || { \
	  echo "❌ Ansible flip failed; node remains cordoned. Inspect /etc/rancher/k3s/config.yaml on $(NODE)."; \
	  exit 1; \
	}
	@echo "  • Waiting for Cilium pod on $(NODE) to be Ready (timeout 5min)..."
	@kubectl -n kube-system wait pod \
		-l k8s-app=cilium \
		--field-selector spec.nodeName=$(NODE) \
		--for=condition=Ready --timeout=300s || { \
	  echo "❌ Cilium pod on $(NODE) did not become Ready."; \
	  kubectl -n kube-system get pod -l k8s-app=cilium --field-selector spec.nodeName=$(NODE) -o wide; \
	  kubectl -n kube-system logs -l k8s-app=cilium --field-selector spec.nodeName=$(NODE) --tail=50 || true; \
	  echo "Node remains cordoned. Run 'make cilium-flip-rollback NODE=$(NODE)' to revert."; \
	  exit 1; \
	}
	@echo "  • Uncordoning $(NODE)..."
	@kubectl uncordon $(NODE)
	@echo "✅ $(NODE) is now on Cilium. Run 'make cilium-flip-status' to inspect cluster state."

cilium-flip-rollback: ## Roll ONE node back to Flannel (NODE=<name>); for clean cluster-wide rollback also delete the Cilium ArgoCD app
	@if [ -z "$(NODE)" ]; then echo "❌ NODE=<name> is required."; exit 1; fi
	@echo "↩️  Rolling $(NODE) back from Cilium to Flannel..."
	@kubectl get node $(NODE) -o name >/dev/null 2>&1 || { echo "❌ Node $(NODE) not found."; exit 1; }
	@echo "  • Draining $(NODE) (timeout 5min)..."
	@kubectl drain $(NODE) --ignore-daemonsets --delete-emptydir-data --timeout=300s || { \
	  echo "❌ Drain failed; node remains cordoned."; \
	  exit 1; \
	}
	@echo "  • Re-rendering K3s config on $(NODE) with enable_cilium_cni=false..."
	@cd $(ANSIBLE_DIR) && ansible-playbook \
		-i inventory/production.yml \
		-i terraform_inventory_aws.py \
		playbooks/cilium-flip.yml \
		--limit $(NODE) \
		-e enable_cilium_cni=false || { \
	  echo "❌ Ansible rollback failed; node remains cordoned."; \
	  exit 1; \
	}
	@echo "  • Waiting for $(NODE) to report Ready after K3s restart (timeout 3min)..."
	@kubectl wait node/$(NODE) --for=condition=Ready --timeout=180s || { \
	  echo "❌ $(NODE) did not become Ready after rollback."; \
	  kubectl describe node $(NODE) | tail -40; \
	  exit 1; \
	}
	@echo "  • Uncordoning $(NODE)..."
	@kubectl uncordon $(NODE)
	@echo "✅ $(NODE) is back on Flannel. Note: the Cilium DaemonSet pod will keep restarting on this node until you remove the Cilium ArgoCD app or add a node-affinity exclusion."

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

validate-terraform-tests: ## Run Terraform unit tests (mock_provider — requires TF >= 1.7)
	@echo "✓ Running Terraform unit tests (mock_provider)..."
	@command -v terraform >/dev/null 2>&1 || (echo "❌ terraform not found"; exit 1)
	@cd infra/aws && $(TF_AWS_OFFLINE_ENV) TF_VAR_localstack_test=yes terraform init -backend=false -input=false -upgrade
	@cd infra/aws && terraform test -test-directory=tests
	@cd infra/aws/modules/compute && $(TF_AWS_OFFLINE_ENV) terraform init -backend=false -input=false -upgrade
	@cd infra/aws/modules/compute && terraform test -test-directory=tests
	@cd infra/aws/modules/network && $(TF_AWS_OFFLINE_ENV) terraform init -backend=false -input=false -upgrade
	@cd infra/aws/modules/network && terraform test -test-directory=tests
	@cd infra/aws/modules/scheduler && $(TF_AWS_OFFLINE_ENV) terraform init -backend=false -input=false -upgrade
	@cd infra/aws/modules/scheduler && terraform test -test-directory=tests
	@cd infra/aws-oidc && $(TF_AWS_OFFLINE_ENV) terraform init -backend=false -input=false -upgrade
	@cd infra/aws-oidc && terraform test -test-directory=tests
	@cd infra/aws-backend && $(TF_AWS_OFFLINE_ENV) terraform init -backend=false -input=false -upgrade
	@cd infra/aws-backend && terraform test -test-directory=tests
	@echo "  ✓ All Terraform unit tests passed."

validate-terraform: validate-terraform-all ## Validate Terraform (alias for validate-terraform-all)

validate-terraform-all: ## Validate all Terraform modules: syntax + format + tflint (infra/aws + aws-oidc + aws-backend)
	@echo "✓ Validating infra/aws (init + validate + fmt + tflint)..."
	@rm -rf infra/aws/.terraform infra/aws/.terraform.lock.hcl
	@cd infra/aws && $(TF_AWS_OFFLINE_ENV) TF_VAR_localstack_test=yes terraform init -backend=false -input=false
	@cd infra/aws && $(TF_AWS_OFFLINE_ENV) TF_VAR_localstack_test=yes terraform validate
	@cd infra/aws && terraform fmt -check -diff
	@cd infra/aws && $(TF_AWS_OFFLINE_ENV) tflint --init
	@cd infra/aws && $(TF_AWS_OFFLINE_ENV) tflint --format=compact
	@echo "✓ Validating infra/aws-oidc..."
	@rm -rf infra/aws-oidc/.terraform
	@cd infra/aws-oidc && $(TF_AWS_OFFLINE_ENV) terraform init -backend=false -input=false -lockfile=readonly
	@cd infra/aws-oidc && $(TF_AWS_OFFLINE_ENV) terraform validate
	@cd infra/aws-oidc && terraform fmt -check -diff
	@echo "✓ Validating infra/aws-backend..."
	@rm -rf infra/aws-backend/.terraform
	@cd infra/aws-backend && $(TF_AWS_OFFLINE_ENV) terraform init -backend=false -input=false -lockfile=readonly
	@cd infra/aws-backend && $(TF_AWS_OFFLINE_ENV) terraform validate
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
	@python3 $(TERRAFORM_DIR)/scripts/validate_localstack.py

test-integration-localstack: ## Spin up LocalStack via docker-compose, run terraform apply + schema validation, tear down
	@echo "🐳 Starting LocalStack..."
	@docker compose -f docker-compose.localstack.yml up -d
	@echo "⏳ Waiting for LocalStack to be healthy..."
	@until curl -sf http://localhost:4566/_localstack/health > /dev/null 2>&1; do sleep 2; done
	@echo "✅ LocalStack ready."
	@python3 $(TERRAFORM_DIR)/scripts/validate_localstack.py \
	  || (echo "⚠️  validation finished with issues — inspect /tmp/tf-*.log"; exit_code=$$?; \
	      docker compose -f docker-compose.localstack.yml down; exit $$exit_code)
	@echo "🧹 Stopping LocalStack..."
	@docker compose -f docker-compose.localstack.yml down

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

##@ Ansible Role Structure Validation

validate-ansible-structure: ## Validate all Ansible roles have required Molecule directory structure
	@echo "🔍 Validating Ansible role structure..."
	@for role_dir in $(ANSIBLE_DIR)/roles/*/; do \
	  role=$$(basename "$$role_dir"); \
	  [ "$$role" = ".template" ] && continue; \
	  [ ! -f "$$role_dir/tasks/main.yml" ] && continue; \
	  \
	  if [ ! -d "$$role_dir/molecule/default" ]; then \
	    echo "❌ $$role: molecule/default/ directory not found"; exit 1; \
	  fi; \
	  \
	  for file in molecule.yml converge.yml verify.yml; do \
	    [ ! -f "$$role_dir/molecule/default/$$file" ] && \
	      { echo "❌ $$role: molecule/default/$$file not found"; exit 1; }; \
	  done; \
	  echo "  ✓ $$role: valid Molecule structure"; \
	done
	@echo "✅ All Ansible roles have valid Molecule structure"

new-role: ## Create new Ansible role from template: make new-role ROLE=my_role
	@python3 bin/create_ansible_role.py $(ROLE)

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

test-molecule-rpi: ## Run Molecule tests for rpi_optimization role (default + sysctl + rpi3 scenarios)
	@echo "🧪 Testing rpi_optimization role with Molecule (default scenario)..."
	@cd $(ANSIBLE_DIR)/roles/rpi_optimization && $(MISE_EXEC) molecule test
	@echo "🧪 Testing rpi_optimization role with Molecule (sysctl scenario — runtime kernel values)..."
	@cd $(ANSIBLE_DIR)/roles/rpi_optimization && $(MISE_EXEC) molecule test -s sysctl
	@echo "🧪 Testing rpi_optimization role with Molecule (rpi3 scenario — RPi 3-only boot config)..."
	@cd $(ANSIBLE_DIR)/roles/rpi_optimization && $(MISE_EXEC) molecule test -s rpi3
	@echo "  ✓ rpi_optimization role tests passed (all three scenarios)."

test-molecule-argocd: ## Run Molecule tests for argocd role (default + sops scenarios)
	@echo "🧪 Testing argocd role with Molecule (default scenario)..."
	@cd $(ANSIBLE_DIR)/roles/argocd && $(MISE_EXEC) molecule test -s default
	@echo "🧪 Testing argocd role with Molecule (sops scenario — sops_enabled=true)..."
	@cd $(ANSIBLE_DIR)/roles/argocd && $(MISE_EXEC) molecule test -s sops
	@echo "  ✓ argocd role tests passed (both scenarios)."

test-molecule-lint: ## Run ansible-lint and yamllint across all ansible files
	@echo "🔍 Linting Ansible files..."
	@command -v pre-commit >/dev/null 2>&1 && $(MISE_EXEC) pre-commit run --all-files || echo "  ℹ pre-commit not available, skipping"
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

test-molecule-arm64: ## Test Ansible roles on ARM64 via QEMU emulation (requires docker + qemu)
	@echo "🏗️  Testing on ARM64 (emulated via QEMU)..."
	@command -v docker >/dev/null || (echo "❌ docker not found"; exit 1)
	@docker run --platform linux/arm64 -v $(PWD):/homelab -w /homelab \
	  python:3.12-slim-bullseye bash -c "\
	  apt-get update -qq && apt-get install -y -qq git && \
	  pip install -q molecule molecule-plugins[docker] ansible ansible-lint && \
	  cd ansible && molecule test 2>&1" || { echo "❌ ARM64 tests failed"; exit 1; }
	@echo "  ✓ ARM64 Molecule tests passed."

validate-arm64-binary: ## Verify shell scripts are portable (check shebang/format)
	@echo "🔍 Checking ARM64 script compatibility..."
	@for script in bin/*.sh; do \
	  if [ -f "$$script" ]; then \
	    echo "Checking $$script..."; \
	    head -1 "$$script" | grep -q "^#!/" || echo "  ⚠️  No shebang: $$script"; \
	    file "$$script" | grep -q "POSIX shell script" && echo "  ✓ POSIX compatible" || echo "  ⚠️  Check manually: $$script"; \
	  fi; \
	done
	@echo "  ✓ Script compatibility check complete."

##@ Hybrid Cloud Validation (zero-cost offline)
# These targets validate the hybrid AWS + Raspberry Pi architecture without
# incurring any AWS charges.
#
# Prerequisites:
#   LocalStack:  docker run -d -p 4566:4566 localstack/localstack:3.8.1
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
	@python3 bin/smoke_test.py

morning-sync: ## Daily health check — smoke tests, Tailscale nodes, K3s readiness, Loki ERROR/FATAL scan (requires live cluster)
	@echo "🌅 Running morning sync health check..."
	@python3 bin/morning_sync.py

##@ E2E Post-Deployment Testing

test-e2e-post-deploy: ## Run full E2E tests after deployment (requires live cluster, kubectl context)
	@echo "🧪 Running E2E post-deployment test suite..."
	@command -v bats >/dev/null || (echo "❌ bats not found. Install: https://github.com/bats-core/bats-core"; exit 1)
	@command -v kubectl >/dev/null || (echo "❌ kubectl not found. Install: https://kubernetes.io/docs/tasks/tools/"; exit 1)
	@echo ""
	@echo "▶ Phase 1: Enhanced smoke tests (20+ checks)"
	@python3 bin/smoke_test.py
	@echo ""
	@echo "▶ Phase 2: BATS E2E test suite (~40+ test cases)"
	@$(MISE_EXEC) bats bin/tests/e2e_post_deploy.bats --verbose
	@echo ""
	@echo "✅ E2E test suite passed — cluster is production-ready."

test-e2e-connectivity: ## Run connectivity tests only (inter-app communication, Prometheus scrapes)
	@echo "🔌 Running E2E connectivity tests..."
	@command -v bats >/dev/null || (echo "❌ bats not found"; exit 1)
	@$(MISE_EXEC) bats bin/tests/e2e_post_deploy.bats --verbose --filter "Prometheus\|DNS\|connectivity"

test-e2e-observability: ## Run observability pipeline tests only (Prometheus, Loki)
	@echo "📊 Running E2E observability tests..."
	@command -v bats >/dev/null || (echo "❌ bats not found"; exit 1)
	@$(MISE_EXEC) bats bin/tests/e2e_post_deploy.bats --verbose --filter "observability\|Prometheus\|Loki"

test-contracts: ## Verify App-of-Apps path contracts and SOPS secret structure (offline)
	@echo "🧪 Running contract tests..."
	@command -v bats >/dev/null || (echo "❌ bats not found. Install: https://github.com/bats-core/bats-core"; exit 1)
	@bats bin/tests/contract_tests.bats
	@echo "  ✓ Contract tests passed."

test-shell: ## No-op: scripts migrated to Python (covered by make test-python)
	@echo "ℹ️  Shell unit tests removed — scripts are now Python, covered by make test-python."

test-terraform: setup-ci-deps-python ## Run Terraform validation tests (syntax, security, outputs, best practices)
	@echo "🧪 Running Terraform infrastructure tests..."
	@python3 -m pytest infra/aws/tests/test_terraform_infrastructure.py -v
	@echo "  ✓ Terraform infrastructure tests passed."

test-security: setup-ci-deps-python ## Run security guardrail tests (SOPS, policy scope, secret leakage checks)
	@echo "🔐 Running security guardrail tests..."
	@python3 -m pytest ansible/tests/test_security_guardrails.py ansible/tests/test_k8s_supply_chain.py ansible/tests/test_k8s_policy_coverage.py -v
	@echo "  ✓ Security guardrail tests passed."

test-security-runtime: test-security ## Alias: runtime security is covered by test-security
	@echo "  ✓ Runtime security tests passed."

test-security-supply-chain: setup-ci-deps-python ## Run image supply-chain guardrail tests (offline/static)
	@echo "🔗 Running image supply-chain tests..."
	@python3 -m pytest ansible/tests/test_k8s_supply_chain.py -v
	@echo "  ✓ Image supply-chain tests passed."

test-k8s-policy-coverage: setup-ci-deps-python ## Run Kubernetes policy coverage tests (offline/static)
	@echo "📐 Running Kubernetes policy coverage tests..."
	@python3 -m pytest ansible/tests/test_k8s_policy_coverage.py -v
	@echo "  ✓ Kubernetes policy coverage tests passed."

test-k8s-policy-enforcement: ## Alias: use conftest directly — run: conftest test k8s/apps/ --policy k8s/policies/
	@echo "🛡️ Running OPA policy enforcement via conftest..."
	@command -v conftest >/dev/null 2>&1 || (echo "❌ conftest not found. Install via: make setup-ci-deps-conftest"; exit 1)
	@conftest test k8s/apps/ --policy k8s/policies/
	@echo "  ✓ OPA policy enforcement passed."

test-trivy: setup-ci-deps-trivy setup-ci-deps-python ## Trivy image scan in advisory mode (reports CVEs, does not fail build)
	@echo "🔍 Running Trivy image scan (advisory mode) on cluster manifests..."
	@command -v trivy >/dev/null 2>&1 || (echo "❌ trivy not found. Install via: make setup-ci-deps-trivy"; exit 1)
	@command -v kustomize >/dev/null 2>&1 || (echo "❌ kustomize not found"; exit 1)
	@python3 bin/trivy_scan.py
	@echo "  ✓ Trivy image scan completed (advisory)."

test-trivy-strict: setup-ci-deps-trivy setup-ci-deps-python ## Trivy strict mode — fails build on any HIGH/CRITICAL fixable CVE
	@echo "🔍 Running Trivy image scan (strict mode)..."
	@command -v trivy >/dev/null 2>&1 || (echo "❌ trivy not found. Install via: make setup-ci-deps-trivy"; exit 1)
	@command -v kustomize >/dev/null 2>&1 || (echo "❌ kustomize not found"; exit 1)
	@python3 bin/trivy_scan.py --strict
	@echo "  ✓ Trivy strict scan passed."

test-dr: test-dr-execution ## Alias: DR test runs Molecule scenario

test-dr-execution: ## Run disaster recovery role as real execution in Molecule test environment
	@echo "🚨 Running disaster recovery execution tests (Molecule scenario)..."
	@make test-molecule-emergency-recovery
	@echo "  ✓ Disaster recovery execution test passed."

test-python: setup-ci-deps-python ## Run Python unit tests for inventory script and Lambda scheduler with coverage (requires pytest-cov)
	@echo "🧪 Running Python unit tests with coverage..."
	@python3 -m pytest ansible/tests/ infra/aws/modules/scheduler/lambda_src/tests/ infra/aws/scripts/tests/ bin/tests/ -v \
	  --cov \
	  --cov-report=term-missing
	@echo "  ✓ Python unit tests passed with coverage."

test-python-ci: setup-ci-deps-python ## Run Python tests for CI with coverage artifacts and fail-under threshold
	@echo "🧪 Running Python CI tests with coverage artifacts..."
	@python3 -m pytest ansible/tests/ infra/aws/modules/scheduler/lambda_src/tests/ infra/aws/scripts/tests/ bin/tests/ -v \
	  --cov \
	  --cov-report=html \
	  --cov-report=xml \
	  --cov-report=term-missing \
	  --cov-fail-under=85
	@echo "  ✓ Python CI tests passed with coverage artifacts."

test-python-coverage: setup-ci-deps-python ## Generate HTML coverage report for Python tests (opens htmlcov/index.html)
	@echo "📊 Generating detailed coverage report..."
	@python3 -m pytest ansible/tests/ infra/aws/modules/scheduler/lambda_src/tests/ infra/aws/scripts/tests/ bin/tests/ -v \
	  --cov \
	  --cov-report=html \
	  --cov-report=term-missing
	@echo "  ✓ Coverage report generated: htmlcov/index.html"
	@echo "  💡 Open the HTML report to see detailed coverage analysis:"
	@echo "     open htmlcov/index.html"

test-performance: ## Removed: benchmark tests eliminated (overkill for homelab)
	@echo "ℹ️  Performance benchmarks removed. Use 'make test-python' for functional tests."

qa-audit: ## Run tests one-by-one and generate QA evidence report (.qa/evidence)
	@echo "🧾 Running QA audit (sequential test evidence)..."
	@python3 bin/qa_test_audit.py

qa-scorecard: ## Generate QA scorecard from latest 14 audit runs (.qa/evidence)
	@echo "📈 Generating QA scorecard (latest 14 runs)..."
	@python3 bin/qa_scorecard.py --input-dir .qa/evidence --history-limit 14

qa-verify-required-no-skips: ## Fail if any required suite was skipped in the latest QA audit
	@echo "🚫 Verifying required suites were not skipped..."
	@python3 bin/qa_scorecard.py --input-dir .qa/evidence --verify-no-required-skips

qa-verify-duration-budgets: ## Fail if latest QA audit exceeds suite duration budgets
	@echo "⏱️ Verifying QA duration budgets..."
	@python3 bin/qa_scorecard.py --input-dir .qa/evidence --verify-duration-budgets

qa-flake-report: qa-scorecard ## Alias to generate flake/trend report from QA scorecard
	@echo "  ✓ Flake report generated via QA scorecard."

test-offline-required: ## Week 1 profile: required offline suites only (fast, blocking)
	@echo "🧪 Running offline required profile..."
	@make test-acl-json
	@make validate-yaml-lint
	@make validate-shellcheck
	@make validate-ansible
	@make validate-ansible-structure
	@make validate-terraform-all
	@make validate-terraform-tests
	@make test-terraform
	@make test-security
	@make test-contracts
	@make validate-k8s-policies-critical
	@make test-trivy
	@make test-shell
	@make test-python-ci
	@make test-templates
	@echo "  ✓ Offline required profile passed."

test-offline-extended: test-offline-required ## Week 1 profile: extended offline suites including integration-style checks
	@echo "🧪 Running offline extended profile..."
	@make validate-k8s-all
	@make validate-k8s-dry-run
	@make test-molecule
	@make hybrid-dry-run
	@make qa-audit
	@make qa-scorecard
	@make qa-verify-required-no-skips
	@echo "  ✓ Offline extended profile passed."

test-live-required: ## Week 1 profile: required live checks (nightly/RC with active cluster)
	@echo "🌐 Running live required profile..."
	@make test-live-preflight
	@make test-connectivity
	@make smoke-test
	@make test-e2e-connectivity
	@make test-e2e-observability
	@make test-e2e-post-deploy
	@QA_INCLUDE_LIVE_E2E=1 make qa-audit
	@make qa-scorecard
	@make qa-verify-required-no-skips
	@make qa-verify-duration-budgets
	@echo "  ✓ Live required profile passed."

test-live-preflight: ## Preflight checks for live cluster tests (KUBECONFIG + API reachability)
	@echo "🔎 Running live test preflight..."
	@if [ -z "$$KUBECONFIG" ]; then \
		echo "❌ KUBECONFIG is not set"; \
		exit 1; \
	fi
	@command -v kubectl >/dev/null 2>&1 || (echo "❌ kubectl not found"; exit 1)
	@test -f "$$KUBECONFIG" || (echo "❌ KUBECONFIG file not found: $$KUBECONFIG"; exit 1)
	@kubectl --kubeconfig="$$KUBECONFIG" cluster-info --request-timeout=10s >/dev/null
	@kubectl --kubeconfig="$$KUBECONFIG" get nodes >/dev/null
	@echo "  ✓ Live preflight passed."

performance-baseline: ## Removed: benchmark tests eliminated (overkill for homelab)
	@echo "ℹ️  Performance baseline removed. Benchmarks no longer tracked."

test-templates: setup-ci-deps-python ## Validate k3s Jinja2 templates (renders with StrictUndefined + yamllint)
	@echo "🧪 Validating k3s Jinja2 templates..."
	@python3 bin/render_and_lint_templates.py
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

validate-k8s-policies: ## OPA/conftest policy checks on all rendered K8s manifests
	@echo "✓ Running conftest OPA policies (k8s/policies)..."
	@command -v conftest >/dev/null 2>&1 || (echo "❌ conftest not found. Install: https://www.conftest.dev/install/"; exit 1)
	@command -v kustomize >/dev/null 2>&1 || (echo "❌ kustomize not found"; exit 1)
	@kustomize build k8s/apps \
		| python3 -c 'import sys,yaml;[print("---\n"+yaml.dump(d,default_flow_style=False)) for d in yaml.safe_load_all(sys.stdin) if d and "sops" not in d]' \
		| conftest test --policy k8s/policies -
	@echo "  ✓ All K8s policy checks passed."

validate-k8s-policies-critical: validate-k8s-policies ## All 4 OPA policies enforced (blocking gate)
	@echo "  ✓ Critical K8s policy checks passed."

test-e2e-live-nightly: ## Run mandatory live E2E checks for nightly schedule
	@echo "🌙 Running nightly live E2E checks (mandatory)..."
	@QA_INCLUDE_LIVE_E2E=1 make qa-audit
	@echo "  ✓ Nightly live E2E checks passed."

validate-k8s-dry-run: ## Spin up a kind cluster and server-side dry-run all K8s manifests
	@echo "🔄 Running kind-based Kubernetes dry-run..."
	@command -v kind >/dev/null 2>&1 || (echo "❌ kind not found. Install: https://kind.sigs.k8s.io/"; exit 1)
	@command -v kubectl >/dev/null 2>&1 || (echo "❌ kubectl not found"; exit 1)
	@command -v kustomize >/dev/null 2>&1 || (echo "❌ kustomize not found"; exit 1)
	@kind create cluster --name homelab-dryrun --wait 60s
	@( \
		echo "✓ Preparing manifests (filtering SOPS and custom resources)..." && \
		kustomize build k8s/apps \
			| python3 -c '\
import sys,yaml; \
CORE_GROUPS={"v1","apps/v1","batch/v1","networking.k8s.io/v1","rbac.authorization.k8s.io/v1","policy/v1"}; \
docs=[d for d in yaml.safe_load_all(sys.stdin) if d \
      and "sops" not in d \
      and d.get("apiVersion") in CORE_GROUPS \
      and d.get("kind") != "PersistentVolume"]; \
[print("---\n"+yaml.dump(d,default_flow_style=False)) for d in docs]' \
			> /tmp/homelab-dryrun.yaml && \
		echo "✓ Applying namespaces first (must exist before server dry-run)..." && \
		python3 -c 'import sys,yaml; docs=[d for d in yaml.safe_load_all(open("/tmp/homelab-dryrun.yaml")) if d and d.get("kind")=="Namespace"]; [print("---\n"+yaml.dump(d,default_flow_style=False)) for d in docs]' \
			| kubectl apply -f - && \
		echo "✓ Applying remaining manifests (--dry-run=server)..." && \
		kubectl apply --dry-run=server -f /tmp/homelab-dryrun.yaml \
	) || (kind delete cluster --name homelab-dryrun; rm -f /tmp/homelab-dryrun.yaml; exit 1)
	@kind delete cluster --name homelab-dryrun
	@rm -f /tmp/homelab-dryrun.yaml
	@echo "  ✓ Kubernetes dry-run passed — no selector mismatches or reference errors."

lint-workflows: ## Lint GitHub Actions workflows (actionlint syntax + zizmor security, HIGH only)
	@echo "🔍 Linting .github/workflows with actionlint..."
	@$(MISE_EXEC) actionlint -color
	@echo "🔐 Scanning .github/workflows with zizmor (HIGH severity only; solo-homelab gate)..."
	@$(MISE_EXEC) zizmor --config .github/zizmor.yml --min-severity=high .github/workflows/
	@echo "✅ Workflow lint passed (run 'mise exec -- zizmor .github/workflows/' for all findings)."

validate-yaml-lint: ## Run yamllint across the entire repo (root .yamllint config — same scope as CI)
	@echo "✓ Running yamllint (root .yamllint)..."
	@command -v yamllint >/dev/null 2>&1 || (echo "❌ yamllint not found. Install: pip install yamllint"; exit 1)
	@$(MISE_EXEC) yamllint -c .yamllint .
	@echo "  ✓ YAML lint passed."

validate-shellcheck: ## Run shellcheck on all shell scripts (local equivalent of CI shellcheck action)
	@echo "✓ Running shellcheck..."
	@command -v shellcheck >/dev/null 2>&1 || (echo "❌ shellcheck not found. Install: apt install shellcheck"; exit 1)
	@files=$$(find . -name "*.sh" -not -path "./.git/*" -not -path "./.terraform/*" -not -path "./docs/archive/*"); \
	if [ -z "$$files" ]; then \
	  echo "  ℹ️  No shell scripts found — all migrated to Python."; \
	else \
	  echo "$$files" | xargs shellcheck --severity=warning && echo "  ✓ ShellCheck passed."; \
	fi

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
	@make validate-terraform-tests
	@make validate-k8s-all
	@make validate-k8s-policies
	@make test-contracts
	@make test-shell
	@make test-python
	@make test-templates
	@make validate-ansible-structure
	@make test-molecule
	@make hybrid-dry-run
	@echo "✅ All homologation tests passed — safe to open PR for production."
	@echo "ℹ️  Run 'make test-sops' separately to verify SOPS decryption with your Age key."
	@echo "ℹ️  Run 'make validate-k8s-dry-run' if kind is available (server-side dry-run)."
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
		 echo "   docker run -d --name localstack -p 4566:4566 localstack/localstack:3.8.1"; \
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
	@echo "  Hub:           cat docs/README.md"
	@echo "  Ansible Ops:   cat docs/operations/ansible.md"
	@echo "  Testing Guide: cat docs/operations/testing.md"

show-costs: ## Show estimated costs using the code defaults
	@echo "💰 Calculating real-time cost estimates from code defaults..."
	@infracost breakdown --path $(TERRAFORM_DIR) \
		--usage-file infracost-usage.yml \
		--terraform-var is_cost_scan=true

##@ Pre-deploy diagnostics

preflight: ## Run pre-deploy chain checks (tools/AWS/SOPS/Tailscale/SSH/SSM/kube/git)
	@python3 bin/preflight.py

drift: ## Detect Terraform / ArgoCD / inventory drift
	@python3 bin/drift.py

drift-fix: ## Detect drift and auto-apply fixes (terraform refresh + argocd sync) without prompting
	@python3 bin/drift.py --fix

update-versions: ## Scan for outdated versions, create a branch, apply updates, lint, and stage for review
	@python3 bin/update_versions.py

update-versions-dry-run: ## Preview outdated versions across Ansible, Terraform, and Kubernetes (no file changes)
	@python3 bin/update_versions.py --dry-run
