# Homelab Infrastructure Management
# Usage: make <target>

.PHONY: help deploy destroy status ansible terraform test clean

# Default target
.DEFAULT_GOAL := help

# Configuration
TERRAFORM_DIR := infra/aws
ANSIBLE_DIR := ansible
DEPLOY_SCRIPT := bin/deploy-aws-homelab.sh

##@ General

help: ## Display this help message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Deployment

deploy: ## Deploy complete AWS infrastructure + k3s cluster + ArgoCD + apps
	@echo "🚀 Starting full deployment..."
	@$(DEPLOY_SCRIPT)

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

##@ Configuration Management

ansible-ping: ## Test Ansible connectivity to all hosts
	@echo "🏓 Pinging all hosts..."
	@cd $(ANSIBLE_DIR) && ansible all -i terraform_inventory_aws.py -m ping

ansible-inventory: ## Show dynamic inventory
	@echo "📋 Dynamic inventory:"
	@cd $(ANSIBLE_DIR) && python3 terraform_inventory_aws.py --list | jq .

ansible-deploy: ## Run Ansible playbook only (assumes infrastructure exists)
	@echo "⚙️  Running Ansible configuration..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml

ansible-check: ## Run Ansible in check mode (dry run)
	@echo "🔍 Ansible check mode..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i terraform_inventory_aws.py playbooks/site.yml --check

ansible-health: ## Run health check playbook
	@echo "💚 Checking cluster health..."
	@cd $(ANSIBLE_DIR) && ansible-playbook -i inventory/production.yml playbooks/maintenance/health_check.yml

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

k8s-kubeconfig: ## Get kubeconfig from k3s server via SSM (Zero Trust)
	@echo "📥 Retrieving kubeconfig via SSM..."
	@cd $(ANSIBLE_DIR) && \
	ansible k3s-server -i terraform_inventory_aws.py -b -m fetch \
		-a "src=/etc/rancher/k3s/k3s.yaml dest=/tmp/k3s-homelab-kubeconfig-raw flat=yes"
	@SERVER_TS_IP=$$(cd $(ANSIBLE_DIR) && python3 terraform_inventory_aws.py --host k3s-server | jq -r .tailscale_ip); \
	sed -i "s|127.0.0.1|$$SERVER_TS_IP|g" /tmp/k3s-homelab-kubeconfig-raw && \
	mv /tmp/k3s-homelab-kubeconfig-raw /tmp/k3s-homelab-kubeconfig.yaml
	@echo "✅ Saved to /tmp/k3s-homelab-kubeconfig.yaml (configured for Tailscale IP)"
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

test: ## Run all tests
	@echo "🧪 Running tests..."
	@make test-terraform
	@make test-ansible
	@make test-connectivity

test-terraform: ## Validate Terraform configuration
	@echo "✓ Testing Terraform..."
	@cd $(TERRAFORM_DIR) && terraform validate

test-ansible: ## Validate Ansible playbooks
	@echo "✓ Testing Ansible syntax..."
	@cd $(ANSIBLE_DIR) && ansible-playbook playbooks/site.yml --syntax-check

test-connectivity: ## Test SSH connectivity to instances
	@echo "✓ Testing SSH connectivity..."
	@SERVER_IP=$$(cd $(TERRAFORM_DIR) && terraform output -raw k3s_server_public_ip 2>/dev/null); \
	if [ -n "$$SERVER_IP" ]; then \
		ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i ~/.ssh/homelab-aws ec2-user@$$SERVER_IP "echo '  Server: OK'" || echo "  Server: FAILED"; \
	fi

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

show-costs: ## Show estimated AWS costs
	@echo "💰 Estimated Monthly Costs:"
	@echo "  EC2 Spot Instances: ~\$12.41/month (2x t3.small)"
	@echo "  EBS Storage: ~\$3.20/month (40GB)"
	@echo "  Lambda: Free tier (negligible)"
	@echo "  Data Transfer: ~\$1/month"
	@echo "  ─────────────────────────────"
	@echo "  TOTAL: ~\$24.59/month"
