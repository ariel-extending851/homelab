# OCI + K3s Homelab Evolution: Platform Engineering & DevSecOps Implementation Plan

**Author:** Platform Engineering Candidate
**Date:** February 2026
**Current Role:** SysAdmin → Platform Engineer
**Target:** Big Tech / Startup DevOps/Platform Engineering Interviews

---

## Executive Summary

This document outlines a strategic roadmap to transform a foundational OCI + K3s homelab into a production-grade, DevSecOps-compliant platform that demonstrates enterprise-level platform engineering competencies. The evolution follows a **Zero Trust Architecture** with defense-in-depth security, GitOps workflows, and policy-as-code governance.

**Key Objectives:**
1. **Identity & Access:** Migrate to Tailscale OAuth for seamless, secure networking
2. **Security Automation:** Implement CI/CD security gates with Trivy and Checkov
3. **Policy Governance:** Enforce security policies via Kyverno (Policy-as-Code)
4. **Secret Lifecycle:** Automate secret management with External Secrets Operator

---

## Phase 1: Foundation & Identity Modernization (Weeks 1-2)

### 1.1 Tailscale OAuth Migration

**Current State:** Expiring auth keys require manual rotation
**Target State:** OAuth 2.0 Client Credentials with automatic rotation

#### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Tailscale Control Plane                   │
│  ┌──────────────────┐          ┌────────────────────────┐  │
│  │ OAuth Client     │──────────▶│ Machine Auth (OCI)     │  │
│  │ (Terraform)      │          │ (Non-expiring)         │  │
│  └──────────────────┘          └────────────────────────┘  │
│           │                                                  │
│           ▼                                                  │
│  ┌──────────────────┐          ┌────────────────────────┐  │
│  │ K8s Operator     │──────────▶│ OAuth Client Secret    │  │
│  │ (long-lived)     │          │ (K8s Secret)           │  │
│  └──────────────────┘          └────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

#### Implementation Steps

**Step 1: Create Tailscale OAuth Client**

1. Navigate to Tailscale Admin Console → Settings → OAuth Clients
2. Create new client with scopes:
   - `devices` (read, write) - for VM registration
   - `auth_keys` (write) - for K8s operator
   - `tailnet` (read) - for network discovery

**Step 2: Update Terraform for OCI VMs**

```hcl
# infra/oci/modules/compute/tailscale-oauth.tf

# Store OAuth credentials in SOPS
locals {
  tailscale_oauth = {
    client_id     = local.secrets["tailscale_oauth_client_id"]
    client_secret = local.secrets["tailscale_oauth_client_secret"]
  }
}

# Generate auth key via Tailscale API (valid for 1 hour, non-reusable)
data "http" "tailscale_auth_key" {
  url    = "https://api.tailscale.com/api/v2/tailnet/-/keys"
  method = "POST"

  headers = {
    Authorization = "Basic ${base64encode("${local.tailscale_oauth.client_id}:${local.tailscale_oauth.client_secret}")}"
    Content-Type  = "application/json"
  }

  request_body = jsonencode({
    capabilities = {
      devices = {
        create = {
          reusable      = false
          ephemeral     = true
          preauthorized = true
          tags          = ["tag:oci-vm", "tag:k3s-node"]
        }
      }
    }
    expirySeconds = 3600  # 1 hour - just enough for provisioning
  })
}

# Cloud-init script for VM boot
locals {
  cloud_init = templatefile("${path.module}/templates/cloud-init.yaml", {
    tailscale_auth_key = jsondecode(data.http.tailscale_auth_key.response_body).key
    # ... other vars
  })
}
```

**Step 3: Update K8s Tailscale Operator**

```yaml
# k8s/system/tailscale-operator/values-oauth.yaml
operatorConfig:
  hostname: "k3s-cluster-operator"

# OAuth credentials stored as K8s secret (synced from SOPS via ESO later)
# For now, manual creation:
# kubectl create secret generic tailscale-oauth-credentials \
#   --from-literal=client-id=$TS_OAUTH_CLIENT_ID \
#   --from-literal=client-secret=$TS_OAUTH_CLIENT_SECRET \
#   -n tailscale-operator

authKey: ""  # Disable legacy auth key
oauth:
  clientId:
    secretName: "tailscale-oauth-credentials"
    secretKey: "client-id"
  clientSecret:
    secretName: "tailscale-oauth-credentials"
    secretKey: "client-secret"
```

**Step 4: SOPS Secret Structure Update**

```yaml
# terraform.tfvars.sops.yaml additions:
tailscale_oauth_client_id: "tskey-client-xxx"
tailscale_oauth_client_secret: "tskey-client-secret-xxx"
```

---

### 1.2 Git Repository Structure for Platform Engineering

```
.
├── .github/
│   └── workflows/
│       ├── devsecops-scan.yaml      # Phase 2
│       ├── terraform-deploy.yaml
│       └── k8s-deploy.yaml
├── docs/
│   ├── architecture/
│   │   ├── 00-zero-trust-overview.md
│   │   ├── 01-network-security.md
│   │   └── 02-secret-management.md
│   └── runbooks/
├── infra/
│   ├── oci/
│   │   ├── modules/
│   │   │   ├── network/
│   │   │   ├── compute/
│   │   │   └── iam/
│   │   ├── main.tf
│   │   ├── github.tf
│   │   ├── variables.tf
│   │   └── terraform.tfvars.sops.yaml
│   └── policies/                    # Phase 3
│       └── kyverno/
├── k8s/
│   ├── apps/
│   ├── gitops/
│   ├── system/
│   └── policies/
├── scripts/
│   ├── setup-sops.sh
│   └── rotate-tailscale-keys.sh
└── .pre-commit-config.yaml          # Phase 2
```

---

## Phase 2: DevSecOps Pipeline Implementation (Weeks 3-4)

### 2.1 GitHub Actions Security Gates

**Goal:** Block deployments with vulnerabilities or misconfigurations

#### Workflow Architecture

```yaml
# .github/workflows/devsecops-scan.yaml
name: DevSecOps Security Scan

on:
  pull_request:
    branches: [main, develop]
    paths:
      - 'infra/**'
      - 'k8s/**'
      - '.github/workflows/**'
  push:
    branches: [main]

env:
  TRIVY_VERSION: "0.48.0"
  CHECKOV_VERSION: "3.1.0"

jobs:
  # ─────────────────────────────────────────────────────────────
  # Job 1: Terraform Security & Compliance Scan
  # ─────────────────────────────────────────────────────────────
  terraform-scan:
    name: Terraform IaC Security
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
      pull-requests: write

    steps:
      - name: Checkout Repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.7.0"

      - name: Terraform Format Check
        id: fmt
        run: terraform fmt -check -recursive infra/
        continue-on-error: true

      - name: Terraform Init (Mock)
        run: |
          cd infra/oci
          terraform init -backend=false

      - name: Run Checkov - Terraform
        id: checkov
        uses: bridgecrewio/checkov-action@master
        with:
          directory: infra/
          framework: terraform
          output_format: sarif
          output_file_path: reports/checkov-terraform.sarif
          soft_fail: false  # Hard fail on violations
          # Skip checks that don't apply to homelab
          skip_check: "CKV_OCI_1,CKV_OCI_2"  # Example: skip specific OCI checks

      - name: Run Trivy - Terraform Config
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'config'
          scan-ref: './infra'
          format: 'sarif'
          output: 'reports/trivy-terraform.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'  # Fail on CRITICAL/HIGH

      - name: Upload SARIF to GitHub Security Tab
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: reports/
          category: terraform-scan

      - name: Comment PR with Results
        if: github.event_name == 'pull_request' && failure()
        uses: actions/github-script@v7
        with:
          script: |
            const message = `❌ **DevSecOps Scan Failed**

            | Tool | Status | Details |
            |------|--------|---------|
            | Checkov | ${'${{ steps.checkov.outcome }}'} | Terraform compliance |
            | Trivy | ${'${{ steps.trivy.outcome }}'} | IaC vulnerabilities |

            Please fix the issues before merging.`;

            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: message
            });

  # ─────────────────────────────────────────────────────────────
  # Job 2: Kubernetes Manifest Security Scan
  # ─────────────────────────────────────────────────────────────
  k8s-manifest-scan:
    name: K8s Manifest Security
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Run Checkov - Kubernetes
        uses: bridgecrewio/checkov-action@master
        with:
          directory: k8s/
          framework: kubernetes
          output_format: sarif
          output_file_path: reports/checkov-k8s.sarif
          soft_fail: false

      - name: Run Trivy - K8s YAML
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: 'config'
          scan-ref: './k8s'
          format: 'sarif'
          output: 'reports/trivy-k8s.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'

      - name: Run Kubesec (Additional)
        run: |
          # Install kubesec
          wget -O kubesec https://github.com/controlplaneio/kubesec/releases/download/v2.14.2/kubesec_linux_amd64
          chmod +x kubesec

          # Scan all YAML files
          find k8s/ -name "*.yaml" -type f | while read file; do
            echo "Scanning: $file"
            ./kubesec scan "$file" || true
          done

      - name: Upload SARIF Results
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: reports/
          category: k8s-manifest-scan

  # ─────────────────────────────────────────────────────────────
  # Job 3: Container Image Scan (for custom images)
  # ─────────────────────────────────────────────────────────────
  container-scan:
    name: Container Image Security
    runs-on: ubuntu-latest
    if: contains(github.event.head_commit.message, 'container:') || github.event_name == 'pull_request'

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Build Test Image (if Dockerfile changed)
        run: |
          if [ -f "containers/Dockerfile" ]; then
            docker build -t test-image:latest containers/
          fi

      - name: Trivy Image Scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: 'test-image:latest'
          format: 'sarif'
          output: 'reports/trivy-image.sarif'
          severity: 'CRITICAL,HIGH'
          exit-code: '1'

  # ─────────────────────────────────────────────────────────────
  # Job 4: SOPS Encryption Verification
  # ─────────────────────────────────────────────────────────────
  sops-validation:
    name: Secret Encryption Check
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install SOPS
        run: |
          wget -O sops https://github.com/getsops/sops/releases/download/v3.8.1/sops-v3.8.1.linux.amd64
          chmod +x sops
          sudo mv sops /usr/local/bin/

      - name: Verify All Secrets Encrypted
        run: |
          UNENCRYPTED=$(find . -name "*.yaml" -o -name "*.json" | while read f; do
            if grep -q "^sops:$" "$f" 2>/dev/null; then
              continue  # Already encrypted
            fi
            # Check for sensitive patterns
            if grep -Ei "(password|secret|key|token|ocid).*:" "$f" 2>/dev/null | grep -v "^#"; then
              echo "$f"
            fi
          done)

          if [ -n "$UNENCRYPTED" ]; then
            echo "❌ Unencrypted secrets found in:"
            echo "$UNENCRYPTED"
            exit 1
          fi

          echo "✅ All secrets properly encrypted"

  # ─────────────────────────────────────────────────────────────
  # Final Gate: Deployment Approval
  # ─────────────────────────────────────────────────────────────
  security-gate:
    name: Security Gate
    runs-on: ubuntu-latest
    needs: [terraform-scan, k8s-manifest-scan, sops-validation]
    if: always()

    steps:
      - name: Evaluate All Checks
        run: |
          if [ "${{ needs.terraform-scan.result }}" != "success" ] || \
             [ "${{ needs.k8s-manifest-scan.result }}" != "success" ] || \
             [ "${{ needs.sops-validation.result }}" != "success" ]; then
            echo "❌ Security gate failed - deployment blocked"
            exit 1
          fi
          echo "✅ All security checks passed"
```

---

### 2.2 Pre-Commit Hooks (Local Development)

```yaml
# .pre-commit-config.yaml
repos:
  # Terraform validation
  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.86.0
    hooks:
      - id: terraform_fmt
      - id: terraform_validate
      - id: terraform_tflint
        args:
          - --args=--config=.tflint.hcl
      - id: terraform_tfsec
        args:
          - --args=--config-file=.tfsec.json

  # SOPS verification
  - repo: local
    hooks:
      - id: sops-check
        name: Check SOPS encryption
        entry: scripts/check-sops-encryption.sh
        language: script
        files: \.(yaml|json)$
        pass_filenames: true

  # General security
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: detect-private-key
      - id: detect-aws-credentials

  # Gitleaks - comprehensive secret scanning
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.1
    hooks:
      - id: gitleaks
        args: ["--verbose", "--redact"]
```

---

## Phase 3: Policy-as-Code with Kyverno (Weeks 5-6)

### 3.1 Kyverno Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         K3s Cluster                                 │
│  ┌──────────────────────┐         ┌──────────────────────────┐    │
│  │ Admission Controller │◄────────│ Kyverno Policies         │    │
│  │ (API Server)         │         │                          │    │
│  └──────────────────────┘         │ • Require Tailscale      │    │
│           │                        │ • Deny Privileged        │    │
│           │                        │ • Enforce Labels         │    │
│           ▼                        │ • Resource Limits        │    │
│  ┌──────────────────────┐         └──────────────────────────┘    │
│  │ Pod/Deployment       │                                          │
│  │ (ALLOW/DENY)         │                                          │
│  └──────────────────────┘                                          │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 Core Policies

#### Policy 1: Require Tailscale for All Services

```yaml
# k8s/policies/kyverno/require-tailscale-ingress.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-tailscale-ingress
  annotations:
    policies.kyverno.io/title: Require Tailscale Ingress
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: high
    policies.kyverno.io/subject: Service
    policies.kyverno.io/description: |
      Ensures all LoadBalancer and NodePort services use Tailscale
      for secure access. Prevents accidental public exposure.
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: check-tailscale-annotation
      match:
        resources:
          kinds:
            - Service
          selector:
            matchExpressions:
              - key: app.kubernetes.io/managed-by
                operator: NotIn
                values:
                  - tailscale-operator
      exclude:
        resources:
          namespaces:
            - kube-system
            - tailscale
      validate:
        message: "All LoadBalancer/NodePort services must use Tailscale (ts.net)"
        pattern:
          metadata:
            annotations:
              tailscale.com/expose: "true"
          spec:
            type: "LoadBalancer"
            selector:
              tailscale.com/exposed-via: "?*"
```

#### Policy 2: Deny Privileged Containers

```yaml
# k8s/policies/kyverno/deny-privileged-containers.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-privileged-containers
  annotations:
    policies.kyverno.io/title: Deny Privileged Containers
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: critical
    policies.kyverno.io/subject: Pod
    policies.kyverno.io/description: |
      Prevents containers from running in privileged mode.
      Exception process required via label.
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: deny-privileged
      match:
        resources:
          kinds:
            - Pod
      exclude:
        resources:
          selector:
            matchLabels:
              security.kyverno.io/privileged-exception: "approved"
      validate:
        message: "Privileged containers are forbidden. Request exception via platform team."
        pattern:
          spec:
            =(initContainers):
              - =(securityContext):
                  =(privileged): "false"
            containers:
              - =(securityContext):
                  =(privileged): "false"
```

#### Policy 3: Enforce Resource Limits

```yaml
# k8s/policies/kyverno/require-resource-limits.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-limits
  annotations:
    policies.kyverno.io/title: Require Resource Limits
    policies.kyverno.io/category: Best Practices
    policies.kyverno.io/severity: medium
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: validate-resources
      match:
        resources:
          kinds:
            - Pod
      exclude:
        resources:
          namespaces:
            - kube-system
      validate:
        message: "All containers must have CPU/memory limits and requests"
        pattern:
          spec:
            containers:
              - resources:
                  limits:
                    memory: "?*"
                    cpu: "?*"
                  requests:
                    memory: "?*"
                    cpu: "?*"
```

#### Policy 4: Enforce Network Policies

```yaml
# k8s/policies/kyverno/require-network-policy.yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-network-policy
  annotations:
    policies.kyverno.io/title: Require Network Policy
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: medium
spec:
  validationFailureAction: Audit
  background: true
  rules:
    - name: check-network-policy
      match:
        resources:
          kinds:
            - Namespace
      preconditions:
        - key: "{{request.object.metadata.labels.istio-injection}}"
          operator: NotEquals
          value: "enabled"
      validate:
        message: "Namespace must have a NetworkPolicy"
        deny:
          conditions:
            - key: "{{request.object.metadata.labels.network-policy-applied}}"
              operator: NotEquals
              value: "true"
```

---

### 3.3 Kyverno Installation (K3s)

```bash
# Install Kyverno via Helm
helm repo add kyverno https://kyverno.github.io/kyverno/
helm repo update

helm install kyverno kyverno/kyverno \
  --namespace kyverno \
  --create-namespace \
  --set admissionController.replicas=1 \
  --set backgroundController.replicas=1 \
  --set cleanupController.replicas=1 \
  --set reportsController.replicas=1

# Apply policies
kubectl apply -f k8s/policies/kyverno/
```

---

## Phase 4: Advanced Secret Management with External Secrets Operator (Weeks 7-8)

### 4.1 ESO Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Secret Management Flow                            │
│                                                                      │
│   ┌──────────────────┐         ┌──────────────────────────┐        │
│   │ External Source  │         │ External Secrets         │        │
│   │ (SOPS/OCI Vault) │────────▶│ Operator (ESO)           │        │
│   └──────────────────┘         └──────────┬───────────────┘        │
│            │                              │                        │
│            │                              ▼                        │
│   ┌────────▼──────────┐         ┌──────────────────────────┐       │
│   │ SOPS File         │         │ ClusterSecretStore       │       │
│   │ terraform.tfvars  │         │ (authenticates to SOPS)  │       │
│   └───────────────────┘         └──────────┬───────────────┘       │
│                                            │                       │
│                                            ▼                       │
│                              ┌──────────────────────────┐         │
│                              │ ExternalSecret           │         │
│                              │ (syncs to K8s Secret)    │         │
│                              └──────────┬───────────────┘         │
│                                         ▼                         │
│                              ┌──────────────────────────┐         │
│                              │ K8s Secret (in-cluster)  │         │
│                              └──────────────────────────┘         │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 ESO Implementation

#### Step 1: Install ESO

```yaml
# k8s/system/external-secrets/helm-values.yaml
installCRDs: true

certController:
  replicaCount: 1

webhook:
  replicaCount: 1

# Use existing Prometheus metrics
serviceMonitor:
  enabled: true
```

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets \
  --create-namespace \
  -f k8s/system/external-secrets/helm-values.yaml
```

#### Step 2: ClusterSecretStore for SOPS

```yaml
# k8s/system/external-secrets/cluster-secret-store-sops.yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: sops-secret-store
  annotations:
    argocd.argoproj.io/sync-wave: "-5"
spec:
  provider:
    # Using SOPS with Age key
    sops:
      # Path to SOPS-encrypted file (mounted via ConfigMap/Secret)
      key: /sops/secrets/terraform.tfvars.sops.yaml
      # Age identity (private key) for decryption
      age:
        keySecret:
          name: sops-age-key
          namespace: external-secrets
          key: age.key
```

#### Step 3: ExternalSecret Resources

```yaml
# k8s/system/external-secrets/external-secrets-oci.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: oci-credentials
  namespace: external-secrets
  annotations:
    argocd.argoproj.io/sync-wave: "-4"
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: sops-secret-store
  target:
    name: oci-credentials
    creationPolicy: Owner
    template:
      type: Opaque
      data:
        tenancy_ocid: "{{ .tenancy_ocid }}"
        user_ocid: "{{ .user_ocid }}"
        fingerprint: "{{ .fingerprint }}"
        private_key_path: "{{ .private_key_path }}"
        compartment_id: "{{ .compartment_id }}"
  data:
    - secretKey: tenancy_ocid
      remoteRef:
        key: tenancy_ocid
    - secretKey: user_ocid
      remoteRef:
        key: user_ocid
    - secretKey: fingerprint
      remoteRef:
        key: fingerprint
    - secretKey: private_key_path
      remoteRef:
        key: private_key_path
    - secretKey: compartment_id
      remoteRef:
        key: compartment_id

---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: tailscale-oauth
  namespace: tailscale-operator
spec:
  refreshInterval: 24h  # OAuth tokens are long-lived
  secretStoreRef:
    kind: ClusterSecretStore
    name: sops-secret-store
  target:
    name: tailscale-oauth-credentials
    creationPolicy: Owner
  data:
    - secretKey: client-id
      remoteRef:
        key: tailscale_oauth_client_id
    - secretKey: client-secret
      remoteRef:
        key: tailscale_oauth_client_secret

---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: github-token
  namespace: flux-system  # or wherever GitOps tools run
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: sops-secret-store
  target:
    name: github-token
    creationPolicy: Owner
  data:
    - secretKey: token
      remoteRef:
        key: github_token
```

---

## Phase 5: Data Persistence & Disaster Recovery (Weeks 9-10)

### Overview: From Manual Backups to Platform-Managed Resilience

**Maturity Evolution:**
- **SysAdmin Era:** Manual `rsync` scripts, cron jobs, "hope it works"
- **Platform Era:** Automated, monitored, tested recovery with defined RTO/RPO

**Recovery Objectives:**
| Metric | Target | Justification |
|--------|--------|---------------|
| **RPO** (Recovery Point Objective) | < 4 hours | Acceptable data loss for homelab media |
| **RTO** (Recovery Time Objective) | < 30 minutes | Critical services (Adguard, monitoring) |
| **Retention** | 30 days daily + 12 monthly | Cost/utility balance for OCI storage |

---

### 5.1 Architecture: Tiered Backup Strategy

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Backup Architecture Overview                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   Tier 1: K3s Cluster (Velero)                                      │
│   ┌──────────────────────┐         ┌──────────────────────────┐    │
│   │ K3s Cluster          │         │ Velero                   │    │
│   │ (Raspberry Pi 4 +    │────────▶│ ├─ Cluster metadata      │    │
│   │  OCI VM.Standard3)   │         │ ├─ PV snapshots (CSI)    │    │
│   └──────────────────────┘         │ └─ App-specific hooks    │    │
│                                     └──────────┬───────────────┘    │
│                                                │                    │
│   Tier 2: Edge Devices (Restic)                │                    │
│   ┌──────────────────────┐                    │                    │
│   │ Raspberry Pi 3       │                    │                    │
│   │ (1GB RAM - legacy)   │────────────────────┘                    │
│   │ Restic (lightweight) │                                         │
│   └──────────────────────┘                                         │
│                                                                     │
│   Unified Backend: OCI Object Storage (S3-Compatible)              │
│   ┌──────────────────────────────────────────────────────────┐     │
│   │  Bucket: homelab-backups-k3s                             │     │
│   │  Bucket: homelab-backups-edge                            │     │
│   │  Bucket: homelab-backups-archive (glacier)               │     │
│   │  Region: Cross-region replication (optional)             │     │
│   └──────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

---

### 5.2 Implementation: Velero for K3s

**Tool Selection Rationale:**
Velero is the industry standard for Kubernetes backup, supporting:
- Namespace-level granular backups
- Persistent Volume snapshots (via CSI)
- Pre/post backup hooks for database consistency
- Migration between clusters (OCI ↔ on-prem)

#### Step 1: OCI Object Storage Infrastructure (Terraform)

```hcl
# infra/oci/modules/backup/main.tf

# S3-Compatible Object Storage Bucket for Velero
resource "oci_objectstorage_bucket" "k3s_backups" {
  compartment_id = var.compartment_id
  name           = "homelab-backups-k3s"
  namespace      = data.oci_objectstorage_namespace.ns.namespace
  storage_tier   = "Standard"

  # Security: Private bucket, no public access
  access_type    = "NoPublicAccess"

  # Enable object versioning for point-in-time recovery
  versioning     = "Enabled"

  # Lifecycle policy: Archive old backups to save costs
  lifecycle_policy {
    rules {
      name     = "archive-old-backups"
      action   = "ARCHIVE"
      time_amount = 30
      time_unit   = "DAYS"
      is_enabled  = true
    }
    rules {
      name     = "delete-very-old-backups"
      action   = "DELETE"
      time_amount = 365
      time_unit   = "DAYS"
      is_enabled  = true
    }
  }

  # Free-form tags for cost tracking
  freeform_tags = {
    "Environment" = "homelab"
    "Purpose"     = "k3s-backup"
    "ManagedBy"   = "terraform"
  }
}

# Generate S3-compatible credentials for Velero
resource "oci_identity_customer_secret_key" "velero_s3_key" {
  display_name = "velero-backup-key"
  user_id      = var.backup_user_ocid
}

# Store credentials in SOPS for ESO to pick up
locals {
  backup_credentials = {
    s3_endpoint = "https://${data.oci_objectstorage_namespace.ns.namespace}.compat.objectstorage.${var.region}.oraclecloud.com"
    s3_bucket   = oci_objectstorage_bucket.k3s_backups.name
    access_key  = oci_identity_customer_secret_key.velero_s3_key.id
    secret_key  = oci_identity_customer_secret_key.velero_s3_key.key
  }
}
```

#### Step 2: Velero Installation (Helm via ArgoCD)

```yaml
# k8s/system/velero/values.yaml
configuration:
  # OCI Object Storage (S3-compatible) backend
  backupStorageLocation:
    - name: oci-object-storage
      provider: aws
      bucket: homelab-backups-k3s
      config:
        region: us-ashburn-1
        s3ForcePathStyle: "true"
        s3Url: "https://xxx.compat.objectstorage.us-ashburn-1.oraclecloud.com"
      default: true

  # CSI snapshot provider for PersistentVolumes
  volumeSnapshotLocation:
    - name: oci-csi
      provider: csi
      config:
        snapshotClass: "oci-bv"

# Credentials from ESO-managed secret
credentials:
  name: "cloud-credentials"
  secretContents:
    aws:
      access_key_id: "{{ .s3_access_key }}"
      aws_secret_access_key: "{{ .s3_secret_key }}"

# Resource limits for Raspberry Pi 4
deployNodeAgent: true
nodeAgent:
  resources:
    requests:
      cpu: "100m"
      memory: "128Mi"
    limits:
      cpu: "500m"
      memory: "256Mi"

# Backup schedules via Schedule CRD (see below)
```

```yaml
# k8s/system/velero/schedule-daily.yaml
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: daily-critical-backup
  namespace: velero
  annotations:
    argocd.argoproj.io/sync-wave: "10"
spec:
  schedule: "0 2 * * *"  # 2 AM daily
  template:
    ttl: "720h"  # 30 days retention
    includedNamespaces:
      - adguard
      - ***
      - monitoring
      - media
    excludedResources:
      - events
      - pods  # Re-created from deployments
    snapshotVolumes: true
    volumeSnapshotLocations:
      - oci-csi
    defaultVolumesToFsBackup: true  # For non-CSI volumes

    # Pre/post hooks for database consistency
    hooks:
      resources:
        - name: database-backup-hook
          includedNamespaces:
            - media
          labelSelector:
            matchLabels:
              app: postgres
          pre:
            - exec:
                container: postgres
                command: ["/bin/sh", "-c", "pg_dumpall > /tmp/pre-backup.sql"]
                onError: Fail
                timeout: 5m
```

#### Step 3: ArgoCD Application

```yaml
# gitops/system/velero-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: velero-backup
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: infrastructure
  source:
    repoURL: https://github.com/ariel99gf/homelab.git
    targetRevision: main
    path: k8s/system/velero
    helm:
      valueFiles:
        - values.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: velero
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

---

### 5.3 Implementation: Restic for Raspberry Pi 3 (Edge Devices)

**Why Restic for RPi3:**
- **Memory Efficient:** < 100MB RAM usage (vs Velero's 200MB+)
- **Deduplication:** Only backs up changed blocks
- **Encryption:** AES-256 by default
- **OCI S3 Compatible:** Native support

```bash
#!/bin/bash
# scripts/setup-rpi3-backup.sh - Run on Raspberry Pi 3

# Install Restic (single binary, ARMv7 compatible)
RESTIC_VERSION="0.16.4"
curl -L -o restic.bz2 "https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_arm.bz2"
bzip2 -d restic.bz2
chmod +x restic
sudo mv restic /usr/local/bin/

# Initialize repository
export RESTIC_REPOSITORY="s3:https://xxx.compat.objectstorage.us-ashburn-1.oraclecloud.com/homelab-backups-edge"
export RESTIC_PASSWORD="$(cat /etc/restic/repo-password)"  # From SOPS
export AWS_ACCESS_KEY_ID="$(cat /etc/restic/s3-access-key)"
export AWS_SECRET_ACCESS_KEY="$(cat /etc/restic/s3-secret-key)"

restic init

# Create backup script
cat << 'EOF' | sudo tee /usr/local/bin/backup-rpi3.sh
#!/bin/bash
# Lightweight backup for RPi3 (1GB RAM)

set -euo pipefail

export RESTIC_REPOSITORY="s3:https://xxx.compat.objectstorage.us-ashburn-1.oraclecloud.com/homelab-backups-edge"
export RESTIC_PASSWORD_FILE="/etc/restic/repo-password"
export AWS_ACCESS_KEY_ID="$(cat /etc/restic/s3-access-key)"
export AWS_SECRET_ACCESS_KEY="$(cat /etc/restic/s3-secret-key)"

# Nice/ionice to avoid overwhelming the system
/usr/local/bin/restic backup \
  --verbose=1 \
  --exclude-caches \
  --exclude-if-present .nobackup \
  --tag "rpi3-$(hostname)" \
  --tag "auto-$(date +%Y%m%d)" \
  /home/pi \
  /etc \
  /var/log \
  /opt

# Keep only last 7 daily backups (RPi3 has limited data)
/usr/local/bin/restic forget \
  --keep-daily 7 \
  --keep-weekly 4 \
  --keep-monthly 3 \
  --prune

EOF

chmod +x /usr/local/bin/backup-rpi3.sh

# Systemd timer (more reliable than cron)
cat << 'EOF' | sudo tee /etc/systemd/system/rpi3-backup.service
[Unit]
Description=Restic Backup for Raspberry Pi 3
After=network.target

[Service]
Type=oneshot
User=root
ExecStart=/usr/local/bin/backup-rpi3.sh
Nice=10
IOSchedulingClass=idle
MemoryMax=150M
EOF

cat << 'EOF' | sudo tee /etc/systemd/system/rpi3-backup.timer
[Unit]
Description=Run RPi3 backup daily at 3 AM

[Timer]
OnCalendar=03:00
RandomizedDelaySec=30m
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable rpi3-backup.timer
sudo systemctl start rpi3-backup.timer
```

---

### 5.4 Observability: Monitoring Backup Health

**Professional Approach:** Backups are useless if they fail silently.

#### Zabbix Monitoring Template

```xml
<!-- monitoring/zabbix/template-backup-monitoring.xml -->
<zabbix_export>
    <template>
        <template>Template App Backup Status</template>
        <items>
            <!-- Velero Backup Success Check -->
            <item>
                <name>Velero: Last Backup Status</name>
                <key>velero.backup.status</key>
                <type>ZABBIX_ACTIVE</type>
                <value_type>TEXT</value_type>
                <triggers>
                    <trigger>
                        <name>Velero: Backup Failed</name>
                        <expression>{Template App Backup Status:velero.backup.status.str("Failed")}=1</expression>
                        <priority>HIGH</priority>
                    </trigger>
                </triggers>
            </item>

            <!-- RPi3 Restic Backup Age -->
            <item>
                <name>Restic: Backup Age (hours)</name>
                <key>restic.backup.age</key>
                <type>ZABBIX_ACTIVE</type>
                <value_type>FLOAT</value_type>
                <triggers>
                    <trigger>
                        <name>Restic: No Backup for 25 Hours</name>
                        <expression>{Template App Backup Status:restic.backup.age.last()}>25</expression>
                        <priority>HIGH</priority>
                    </trigger>
                </triggers>
            </item>
        </items>
    </template>
</zabbix_export>
```

#### Grafana Dashboard (JSON Model)

```json
{
  "dashboard": {
    "title": "Backup Health & RTO Metrics",
    "panels": [
      {
        "title": "Last Successful Backup",
        "type": "stat",
        "targets": [
          {
            "expr": "time() - velero_backup_last_success_timestamp{schedule=\"daily-critical-backup\"}",
            "legendFormat": "Seconds Since Success"
          }
        ],
        "thresholds": {
          "steps": [
            {"color": "green", "value": null},
            {"color": "yellow", "value": 86400},
            {"color": "red", "value": 172800}
          ]
        }
      },
      {
        "title": "Backup Storage Utilization",
        "type": "timeseries",
        "targets": [
          {
            "expr": "oci_objectstorage_bucket_bytes_used{bucket=\"homelab-backups-k3s\"}",
            "legendFormat": "K3s Backups"
          },
          {
            "expr": "oci_objectstorage_bucket_bytes_used{bucket=\"homelab-backups-edge\"}",
            "legendFormat": "Edge Backups"
          }
        ]
      }
    ]
  }
}
```

#### Prometheus ServiceMonitor for Velero

```yaml
# k8s/system/velero/servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: velero-metrics
  namespace: velero
  labels:
    app: velero
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: velero
  endpoints:
    - port: metrics
      interval: 60s
      scrapeTimeout: 30s
      path: /metrics
      metricRelabelings:
        # Only keep metrics we care about
        - sourceLabels: [__name__]
          regex: 'velero_backup_success|velero_backup_failure|velero_backup_duration_seconds'
          action: keep
```

---

### 5.5 Disaster Recovery Runbook

**Professional Standard:** Documented, tested procedures

#### Scenario 1: K3s Cluster Complete Loss

```bash
#!/bin/bash
# runbooks/dr-k3s-total-loss.sh
# RTO Target: 30 minutes

set -euo pipefail

echo "=== K3S CLUSTER DISASTER RECOVERY ==="
echo "Started: $(date)"

# Step 1: Provision new OCI infrastructure (Terraform)
echo "[1/5] Provisioning infrastructure..."
cd /repo/infra/oci
terraform apply -auto-approve -target=module.k3s_nodes
NEW_MASTER_IP=$(terraform output -raw k3s_master_ip)

# Step 2: Install K3s on new nodes (Ansible)
echo "[2/5] Installing K3s..."
ansible-playbook -i hosts.ini playbooks/install-k3s.yaml

# Step 3: Install Velero on new cluster
echo "[3/5] Installing Velero..."
kubectl apply -k k8s/system/velero/

# Step 4: Restore from backup
echo "[4/5] Restoring cluster state..."
velero restore create --from-backup daily-critical-backup --wait

# Step 5: Verify critical services
echo "[5/5] Verifying services..."
kubectl wait --for=condition=ready pod -l app=adguard -n adguard --timeout=300s
kubectl wait --for=condition=ready pod -l app=*** -n *** --timeout=300s

echo "=== RECOVERY COMPLETE ==="
echo "Completed: $(date)"
echo "RTO Achieved: $(( ($(date +%s) - START_TIME) / 60 )) minutes"
```

#### Scenario 2: Application Data Corruption (Point-in-Time Recovery)

```bash
#!/bin/bash
# runbooks/dr-pit-recovery.sh
# RPO Target: < 4 hours

NAMESPACE=${1:-media}
TIMESTAMP=${2:-"2026-02-01 10:00:00"}

echo "=== Point-in-Time Recovery for $NAMESPACE ==="

# Find backup closest to target time
BACKUP=$(velero backup get --output json | \
  jq -r ".items | sort_by(.status.completionTimestamp) |
  map(select(.status.completionTimestamp <= \"$(date -d "$TIMESTAMP" -u +%Y-%m-%dT%H:%M:%SZ)\")) |
  last | .metadata.name")

echo "Selected backup: $BACKUP"

# Restore specific namespace
velero restore create \
  --from-backup "$BACKUP" \
  --include-namespaces "$NAMESPACE" \
  --restore-volumes \
  --wait

echo "=== Recovery Complete ==="
```

---

### 5.6 Professional Portfolio Value

**Interview Talking Points:**

1. **"I designed a tiered backup strategy matching resource constraints"**
   - Velero for high-capacity K3s cluster
   - Restic for memory-constrained RPi3
   - Unified S3-compatible backend

2. **"I defined and monitor SLOs for backup reliability"**
   - RPO < 4 hours (measured via Prometheus)
   - RTO < 30 minutes (tested monthly)
   - 100% backup success rate (alerted on failure)

3. **"I automated disaster recovery runbooks"**
   - Complete cluster restore: 30 min
   - Application-level restore: 5 min
   - Point-in-time recovery: documented

4. **"I implemented cost-conscious storage lifecycle"**
   - OCI Object Storage with auto-archive
   - 30-day hot → 1-year cold → delete
   - Cross-region replication for critical data

---

## Updated Timeline

| Phase | Duration | Key Deliverable |
|-------|----------|-----------------|
| 1 | Weeks 1-2 | Tailscale OAuth + SOPS restructuring |
| 2 | Weeks 3-4 | DevSecOps pipeline operational |
| 3 | Weeks 5-6 | Kyverno policies enforced |
| 4 | Weeks 7-8 | ESO fully deployed |
| **5** | **Weeks 9-10** | **Backup & DR system operational** |
| 6 | Week 11+ | DR drills + documentation |

**New Success Metrics:**
- Backup success rate: 100%
- RTO validated: < 30 minutes (monthly tests)
- RPO validated: < 4 hours (measured)
- Storage cost: <$5/month for OCI buckets

---

## Zero Trust Architecture Principles

### 1. Never Trust, Always Verify

```
┌─────────────────────────────────────────────────────────────────┐
│                    Zero Trust Layers                             │
├─────────────────────────────────────────────────────────────────┤
│  Layer 1: Identity                                               │
│  ├── Tailscale OAuth (no long-lived keys)                       │
│  ├── Device attestation (Tailscale device certs)                │
│  └── mTLS between all services                                  │
│                                                                  │
│  Layer 2: Network                                                │
│  ├── No public IPs (OCI VMs use private subnets)                │
│  ├── All access via Tailscale mesh                              │
│  └── Network Policies (default-deny)                            │
│                                                                  │
│  Layer 3: Application                                            │
│  ├── Kyverno policies enforce security                          │
│  ├── No privileged containers (by default)                      │
│  └── Secrets rotated automatically (ESO)                        │
│                                                                  │
│  Layer 4: Data                                                   │
│  ├── All secrets encrypted at rest (SOPS)                       │
│  ├── Encryption in transit (Tailscale WireGuard)                │
│  └── Audit logging for all access                               │
└─────────────────────────────────────────────────────────────────┘
```

### 2. Least Privilege Access

```hcl
# Example: Terraform IAM with minimal permissions
resource "oci_identity_policy" "platform_engineering" {
  name           = "PlatformEngineeringPolicy"
  description    = "Minimal permissions for homelab automation"
  compartment_id = local.secrets["tenancy_ocid"]

  statements = [
    # Compute - only what we need
    "Allow group PlatformEngineers to manage instances in compartment homelab",
    "Allow group PlatformEngineers to use vnics in compartment homelab",
    "Allow group PlatformEngineers to use subnets in compartment homelab",

    # Network - read-only for most operations
    "Allow group PlatformEngineers to read virtual-network-family in compartment homelab",
    "Allow group PlatformEngineers to manage security-lists in compartment homelab",

    # Explicit deny of dangerous permissions
    "Deny group PlatformEngineers to manage users in tenancy",
    "Deny group PlatformEngineers to manage policies in tenancy",
  ]
}
```

---

## Professional Portfolio Checklist

### For Big Tech Interviews

| Competency | Evidence in Homelab |
|------------|---------------------|
| **IaC Mastery** | Terraform modules with SOPS integration |
| **GitOps** | ArgoCD + GitHub Actions workflows |
| **Security Automation** | Trivy/Checkov in CI/CD pipeline |
| **Policy-as-Code** | Kyverno policies (OSS project experience) |
| **Secret Management** | ESO + SOPS architecture |
| **Zero Trust Networking** | Tailscale OAuth implementation |
| **Observability** | Prometheus/Grafana/Loki stack |
| **Documentation** | Architecture docs and runbooks |

### Key Talking Points

1. **"I implemented defense-in-depth with 4 security gates"**
   - Pre-commit hooks (local)
   - CI/CD scanning (Checkov/Trivy)
   - Admission control (Kyverno)
   - Runtime monitoring (network policies)

2. **"I treat my homelab as a production platform"**
   - SLOs for availability
   - Change management via PRs
   - Incident response runbooks
   - Regular disaster recovery drills

3. **"I automated the entire secret lifecycle"**
   - SOPS for encryption
   - ESO for distribution
   - Rotation policies
   - Audit logging

---

## Phase 6: Cloud-Native Data Platform with CloudNativePG (Weeks 11-13)

### Overview: Database-as-a-Service (DBaaS) for Microservices

**Maturity Evolution:**
- **SysAdmin Era:** Manual PostgreSQL installation, single node, `pg_dump` backups
- **Platform Era:** Self-healing, horizontally-scalable PostgreSQL clusters with automated failover and continuous backups

**Architecture Goals:**
- **High Availability:** 3-node cluster spanning OCI (AMD64) and RPi 4 (ARM64)
- **Data Protection:** Continuous backup to OCI Object Storage via Barman Cloud
- **Security:** Credentials managed via External Secrets Operator
- **Observability:** Complete visibility into query performance, replication lag, and WAL archiving

---

### 6.1 Architecture: Multi-Architecture PostgreSQL Cluster

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    CloudNativePG Cluster Topology                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌──────────────────────────────────────────────────────────────────────┐ │
│   │                     CloudNativePG Operator                           │ │
│   │                    (GitOps-managed via ArgoCD)                       │ │
│   └──────────────────────────────────────────────────────────────────────┘ │
│                                    │                                        │
│                                    ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐  │
│   │                    PostgreSQL Cluster: "homelab-db"                 │  │
│   │                                                                       │  │
│   │   ┌──────────────────┐         ┌──────────────────┐                 │  │
│   │   │ Primary          │◄────────│ Replica 1        │                 │  │
│   │   │ (OCI - AMD64)    │  Stream │ (RPi 4 - ARM64)  │                 │  │
│   │   │ - Read/Write     │  Repl.  │ - Hot Standby    │                 │  │
│   │   │ - Synchronous    │         │ - Async Fallback │                 │  │
│   │   └────────┬─────────┘         └──────────────────┘                 │  │
│   │            │                                                        │  │
│   │            ▼                                                        │  │
│   │   ┌──────────────────┐                                              │  │
│   │   │ Replica 2        │                                              │  │
│   │   │ (OCI - AMD64)    │                                              │  │
│   │   │ - Hot Standby    │                                              │  │
│   │   │ - Failover Target│                                              │  │
│   │   └────────┬─────────┘                                              │  │
│   │            │                                                        │  │
│   │            ▼                                                        │  │
│   │   ┌──────────────────┐                                              │  │
│   │   │ Barman Cloud     │                                              │  │
│   │   │ (Sidecar)        │                                              │  │
│   │   │ - WAL Archiving  │───────▶ OCI Object Storage (S3)             │  │
│   │   │ - Base Backups   │                                              │  │
│   │   └──────────────────┘                                              │  │
│   └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

### 6.2 Implementation: CNPG Operator Installation

#### Step 1: OCI Object Storage for PostgreSQL Backups (Terraform)

```hcl
# infra/oci/modules/database/backups.tf

# Dedicated bucket for PostgreSQL WAL archiving and base backups
resource "oci_objectstorage_bucket" "postgres_backups" {
  compartment_id = var.compartment_id
  name           = "homelab-postgres-backups"
  namespace      = data.oci_objectstorage_namespace.ns.namespace
  storage_tier   = "Standard"

  access_type    = "NoPublicAccess"
  versioning     = "Enabled"

  # Critical for databases: retain backups for extended period
  lifecycle_policy {
    rules {
      name        = "archive-old-wals"
      action      = "ARCHIVE"
      time_amount = 7
      time_unit   = "DAYS"
      is_enabled  = true
    }
    rules {
      name        = "delete-ancient-backups"
      action      = "DELETE"
      time_amount = 730  # 2 years retention for compliance
      time_unit   = "DAYS"
      is_enabled  = true
    }
  }

  freeform_tags = {
    "Environment" = "homelab"
    "Purpose"     = "postgres-backup"
    "Service"     = "cloudnativepg"
    "ManagedBy"   = "terraform"
  }
}

# Outputs for SOPS integration
output "postgres_backup_bucket" {
  value = oci_objectstorage_bucket.postgres_backups.name
}

output "postgres_s3_endpoint" {
  value = "https://${data.oci_objectstorage_namespace.ns.namespace}.compat.objectstorage.${var.region}.oraclecloud.com"
}
```

#### Step 2: SOPS Secret Structure Update

```yaml
# terraform.tfvars.sops.yaml (additions)
postgres_superuser_password: "<encrypted>"
postgres_app_user_password: "<encrypted>"
postgres_replication_password: "<encrypted>"
postgres_s3_access_key: "<encrypted>"
postgres_s3_secret_key: "<encrypted>"
```

#### Step 3: External Secrets for CloudNativePG

```yaml
# k8s/apps/cloudnativepg/external-secrets.yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: cnpg-superuser-credentials
  namespace: database
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: sops-secret-store
  target:
    name: homelab-db-superuser
    creationPolicy: Owner
    template:
      type: kubernetes.io/basic-auth
      data:
        username: postgres
        password: "{{ .postgres_superuser_password }}"
  data:
    - secretKey: postgres_superuser_password
      remoteRef:
        key: postgres_superuser_password

---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: cnpg-app-credentials
  namespace: database
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: sops-secret-store
  target:
    name: homelab-db-app-user
    creationPolicy: Owner
    template:
      type: kubernetes.io/basic-auth
      data:
        username: app_user
        password: "{{ .postgres_app_user_password }}"
  data:
    - secretKey: postgres_app_user_password
      remoteRef:
        key: postgres_app_user_password

---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: cnpg-barman-credentials
  namespace: database
spec:
  refreshInterval: 24h
  secretStoreRef:
    kind: ClusterSecretStore
    name: sops-secret-store
  target:
    name: homelab-db-barman-s3
    creationPolicy: Owner
    template:
      type: Opaque
      data:
        ACCESS_KEY_ID: "{{ .postgres_s3_access_key }}"
        SECRET_ACCESS_KEY: "{{ .postgres_s3_secret_key }}"
        ENDPOINT: "https://xxx.compat.objectstorage.us-ashburn-1.oraclecloud.com"
        BUCKET: "homelab-postgres-backups"
  data:
    - secretKey: postgres_s3_access_key
      remoteRef:
        key: postgres_s3_access_key
    - secretKey: postgres_s3_secret_key
      remoteRef:
        key: postgres_s3_secret_key
```

#### Step 4: CNPG Operator Installation (ArgoCD)

```yaml
# gitops/system/cnpg-operator.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: cloudnativepg-operator
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: infrastructure
  source:
    repoURL: https://github.com/cloudnative-pg/cloudnative-pg.git
    targetRevision: release-1.22
    path: deploy/helm
    helm:
      values: |
        nameOverride: cnpg
        fullnameOverride: cnpg

        # Minimal resources for homelab
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "500m"
            memory: "256Mi"

        # Disable webhooks for simpler setup (can enable later)
        webhook:
          enabled: true
          port: 9443

        # PodMonitor for Prometheus metrics
        monitoring:
          enabled: true
          customQueriesEnabled: true
          queriesConfigMap:
            name: cnpg-custom-queries
            key: queries
  destination:
    server: https://kubernetes.default.svc
    namespace: cnpg-system
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

---

### 6.3 High Availability Configuration

```yaml
# k8s/apps/cloudnativepg/cluster-homelab.yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: homelab-db
  namespace: database
  annotations:
    argocd.argoproj.io/sync-wave: "5"
spec:
  instances: 3

  # PostgreSQL version (LTS)
  imageName: ghcr.io/cloudnative-pg/postgresql:16.2

  # Storage configuration
  storage:
    size: 20Gi
    storageClass: oci-bv  # OCI Block Volume

  # WAL storage (separate PVC for performance)
  walStorage:
    size: 5Gi
    storageClass: oci-bv

  # Enable replication slots for reliability
  replicationSlots:
    highAvailability:
      enabled: true

  # Anti-affinity: Spread across OCI and RPi 4
  affinity:
    enablePodAntiAffinity: true
    topologyKey: kubernetes.io/hostname
    podAntiAffinityType: required

    # Prefer OCI nodes for primary (more reliable)
    additionalPodAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            labelSelector:
              matchExpressions:
                - key: node-type
                  operator: In
                  values:
                    - oci-amd64
            topologyKey: kubernetes.io/hostname

  # Node selector with preference for OCI
  nodeSelector:
    database-workload: "true"

  tolerations:
    - key: database
      operator: Equal
      value: "true"
      effect: NoSchedule

  # Priority class for critical database workload
  priorityClassName: system-cluster-critical

  # Superuser secret (managed by ESO)
  superuserSecret:
    name: homelab-db-superuser

  # Application user for microservices
  postgresql:
    parameters:
      max_connections: "200"
      shared_buffers: "512MB"
      effective_cache_size: "1536MB"
      maintenance_work_mem: "128MB"
      checkpoint_completion_target: "0.9"
      wal_buffers: "16MB"
      default_statistics_target: "100"
      random_page_cost: "1.1"
      effective_io_concurrency: "200"
      work_mem: "2621kB"
      min_wal_size: "1GB"
      max_wal_size: "4GB"
      max_worker_processes: "4"
      max_parallel_workers_per_gather: "2"
      max_parallel_workers: "4"
      max_parallel_maintenance_workers: "2"

    # Additional databases and users
    pg_hba:
      - host all all 10.0.0.0/8 md5  # Internal network only
      - host all all 10.42.0.0/16 md5  # Pod CIDR

  # Failover configuration
  failoverSwitchoverDelay: 60

  # Switched to replica on OCI if primary fails
  replica:
    enabled: true
    source: homelab-db
```

---

### 6.4 Continuous Backup with Barman Cloud

```yaml
# k8s/apps/cloudnativepg/scheduled-backup.yaml
apiVersion: postgresql.cnpg.io/v1
kind: ScheduledBackup
metadata:
  name: homelab-db-daily-backup
  namespace: database
spec:
  schedule: "0 3 * * *"  # 3 AM daily
  backupOwnerReference: self
  cluster:
    name: homelab-db
  immediate: true

  # S3-compatible storage (OCI Object Storage)
  s3:
    path: "/homelab-db/backups"
    endpoint: "https://xxx.compat.objectstorage.us-ashburn-1.oraclecloud.com"
    region: "us-ashburn-1"
    bucket: "homelab-postgres-backups"

    # Credentials from ESO-managed secret
    credentials:
      name: homelab-db-barman-s3
      key: ACCESS_KEY_ID
      secretKey: SECRET_ACCESS_KEY

    # WAL archiving configuration
    wal:
      compression: gzip
      encryption: AES256
      maxParallel: 2

---
# Real-time WAL archiving configuration
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: homelab-db
  namespace: database
spec:
  # ... (previous config) ...

  backup:
    enabled: true
    retentionPolicy: "30d"  # Keep 30 days of backups

    # Continuous WAL archiving
    barmanObjectStore:
      destinationPath: "s3://homelab-postgres-backups/homelab-db/wal"
      s3Credentials:
        accessKeyId:
          name: homelab-db-barman-s3
          key: ACCESS_KEY_ID
        secretAccessKey:
          name: homelab-db-barman-s3
          key: SECRET_ACCESS_KEY
        region:
          name: homelab-db-barman-s3
          key: REGION
        endpointURL:
          name: homelab-db-barman-s3
          key: ENDPOINT

      # WAL archive settings
      wal:
        compression: gzip
        encryption: AES256
        maxParallel: 2

      # Performance tuning for homelab
      data:
        compression: gzip
        jobs: 2
```

---

### 6.5 Monitoring & Observability

#### Custom Prometheus Queries for CNPG

```yaml
# k8s/apps/cloudnativepg/custom-queries.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: cnpg-custom-queries
  namespace: database
data:
  queries: |
    pg_replication:
      query: |
        SELECT
          CASE WHEN pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn()
          THEN 0
          ELSE EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))
          END AS lag_seconds
      metrics:
        - lag_seconds:
            usage: GAUGE
            description: Replication lag in seconds

    pg_database_size:
      query: |
        SELECT pg_database.datname, pg_database_size(pg_database.datname) AS size
        FROM pg_database
        WHERE pg_database.datname NOT IN ('template0', 'template1')
      metrics:
        - datname:
            usage: LABEL
            description: Database name
        - size:
            usage: GAUGE
            description: Database size in bytes

    pg_active_connections:
      query: |
        SELECT count(*) AS active_connections
        FROM pg_stat_activity
        WHERE state = 'active'
      metrics:
        - active_connections:
            usage: GAUGE
            description: Number of active connections

    pg_transactions_rate:
      query: |
        SELECT
          sum(xact_commit) AS commits,
          sum(xact_rollback) AS rollbacks
        FROM pg_stat_database
      metrics:
        - commits:
            usage: COUNTER
            description: Total committed transactions
        - rollbacks:
            usage: COUNTER
            description: Total rolled back transactions
```

#### Grafana Dashboard for CloudNativePG

```json
{
  "dashboard": {
    "title": "CloudNativePG - Homelab Database Cluster",
    "tags": ["database", "postgres", "cnpg"],
    "timezone": "UTC",
    "panels": [
      {
        "title": "Cluster Health",
        "type": "stat",
        "targets": [
          {
            "expr": "cnpg_pg_up{cluster=\"homelab-db\"}",
            "legendFormat": "Instance {{pod}}"
          }
        ],
        "thresholds": {
          "steps": [
            {"color": "red", "value": 0},
            {"color": "green", "value": 1}
          ]
        }
      },
      {
        "title": "Replication Lag",
        "type": "timeseries",
        "targets": [
          {
            "expr": "cnpg_pg_stat_replication_pg_wal_lsn_diff{cluster=\"homelab-db\"} / 1000000",
            "legendFormat": "Lag (MB) - {{pod}}"
          }
        ],
        "alert": {
          "name": "High Replication Lag",
          "condition": "B",
          "evaluator": {"type": "gt", "params": [100]},
          "reducer": {"type": "avg", "params": []},
          "message": "Replication lag exceeds 100MB"
        }
      },
      {
        "title": "Active Connections",
        "type": "gauge",
        "targets": [
          {
            "expr": "cnpg_pg_stat_activity_count{cluster=\"homelab-db\",state=\"active\"}",
            "legendFormat": "Active"
          },
          {
            "expr": "cnpg_pg_stat_activity_count{cluster=\"homelab-db\",state=\"idle\"}",
            "legendFormat": "Idle"
          }
        ],
        "fieldConfig": {
          "max": 200,
          "thresholds": {
            "steps": [
              {"color": "green", "value": 0},
              {"color": "yellow", "value": 150},
              {"color": "red", "value": 180}
            ]
          }
        }
      },
      {
        "title": "Database Size Growth",
        "type": "timeseries",
        "targets": [
          {
            "expr": "cnpg_pg_database_size_bytes{cluster=\"homelab-db\"} / 1024 / 1024 / 1024",
            "legendFormat": "{{datname}}"
          }
        ],
        "yaxes": [
          {"label": "Size (GB)", "min": 0}
        ]
      },
      {
        "title": "Transaction Rate",
        "type": "timeseries",
        "targets": [
          {
            "expr": "rate(cnpg_pg_stat_database_xact_commit{cluster=\"homelab-db\"}[5m])",
            "legendFormat": "Commits/sec"
          },
          {
            "expr": "rate(cnpg_pg_stat_database_xact_rollback{cluster=\"homelab-db\"}[5m])",
            "legendFormat": "Rollbacks/sec"
          }
        ]
      },
      {
        "title": "Backup Status",
        "type": "table",
        "targets": [
          {
            "expr": "cnpg_backups_count{cluster=\"homelab-db\"}",
            "format": "table",
            "instant": true
          }
        ],
        "columns": [
          {"text": "Backup Count", "value": "Value"},
          {"text": "Last Backup", "value": "Time"}
        ]
      }
    ]
  }
}
```

#### Zabbix Monitoring Template

```xml
<zabbix_export>
  <template>
    <template>Template App CloudNativePG</template>
    <items>
      <item>
        <name>CNPG: Primary Instance Status</name>
        <key>cnpg.primary.status</key>
        <type>ZABBIX_ACTIVE</type>
        <value_type>TEXT</value_type>
        <triggers>
          <trigger>
            <name>CNPG: Primary Instance Down</name>
            <expression>{Template App CloudNativePG:cnpg.primary.status.str("Primary")}=0</expression>
            <priority>DISASTER</priority>
          </trigger>
        </triggers>
      </item>
      <item>
        <name>CNPG: Replication Lag (seconds)</name>
        <key>cnpg.replication.lag</key>
        <type>ZABBIX_ACTIVE</type>
        <value_type>FLOAT</value_type>
        <triggers>
          <trigger>
            <name>CNPG: Replication Lag Critical</name>
            <expression>{Template App CloudNativePG:cnpg.replication.lag.last()}>300</expression>
            <priority>HIGH</priority>
          </trigger>
        </triggers>
      </item>
      <item>
        <name>CNPG: Available Replicas</name>
        <key>cnpg.replicas.available</key>
        <type>ZABBIX_ACTIVE</type>
        <value_type>UINT64</value_type>
        <triggers>
          <trigger>
            <name>CNPG: Insufficient Replicas</name>
            <expression>{Template App CloudNativePG:cnpg.replicas.available.last()}<2</expression>
            <priority>HIGH</priority>
          </trigger>
        </triggers>
      </item>
    </items>
  </template>
</zabbix_export>
```

---

### 6.6 Database Connection for Applications

```yaml
# k8s/apps/media/***/deployment.yaml (example)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ***
  namespace: media
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ***
  template:
    spec:
      containers:
        - name: ***
          image: linuxserver/***:latest
          env:
            - name: POSTGRES_HOST
              value: "homelab-db-rw.database.svc.cluster.local"  # Read-write endpoint
            - name: POSTGRES_PORT
              value: "5432"
            - name: POSTGRES_DB
              value: "***"
            - name: POSTGRES_USER
              valueFrom:
                secretKeyRef:
                  name: homelab-db-app-user
                  key: username
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: homelab-db-app-user
                  key: password
```

---

### 6.7 Professional Portfolio Value

**Interview Talking Points:**

1. **"I built a self-healing, multi-architecture database platform"**
   - 3-node PostgreSQL spanning OCI (AMD64) and RPi 4 (ARM64)
   - Automatic failover with < 60s RTO
   - Cross-architecture compatibility (CNPG handles it)

2. **"I implemented database-as-a-service for microservices"**
   - Application teams get connection strings, not database management
   - ESO-managed credentials rotated automatically
   - Backup/restore fully automated via Barman Cloud

3. **"I defined and monitor database SLOs"**
   - Replication lag < 5 seconds (alerted at 60s)
   - Connection pool utilization tracked
   - Storage growth predictions via Grafana

4. **"I achieved zero-downtime database operations"**
   - Rolling upgrades via CNPG
   - Online backups (WAL archiving)
   - Seamless failovers with connection pooling

---

## Updated Timeline

| Phase | Duration | Key Deliverable |
|-------|----------|-----------------|
| 1 | Weeks 1-2 | Tailscale OAuth + SOPS restructuring |
| 2 | Weeks 3-4 | DevSecOps pipeline operational |
| 3 | Weeks 5-6 | Kyverno policies enforced |
| 4 | Weeks 7-8 | ESO fully deployed |
| 5 | Weeks 9-10 | Backup & DR system operational |
| **6** | **Weeks 11-13** | **CloudNativePG DBaaS operational** |
| 7 | Week 14+ | Full platform documentation |

**New Success Metrics:**
- Database availability: 99.9%
- RTO (failover): < 60 seconds
- RPO (data loss): < 5 minutes (WAL archiving)
- Cross-architecture compatibility: Validated

---

## Next Steps & Timeline

| Phase | Duration | Key Deliverable |
|-------|----------|-----------------|
| 1 | Weeks 1-2 | Tailscale OAuth + SOPS restructuring |
| 2 | Weeks 3-4 | DevSecOps pipeline operational |
| 3 | Weeks 5-6 | Kyverno policies enforced |
| 4 | Weeks 7-8 | ESO fully deployed |
| 5 | Week 9+ | Documentation & portfolio |

**Success Metrics:**
- Zero unencrypted secrets in repository
- 100% of deployments pass security scans
- All services accessed exclusively via Tailscale
- < 5 minutes secret rotation time

---

*This document demonstrates enterprise-grade platform engineering practices suitable for Senior DevOps / Platform Engineer interviews at companies like Google, Amazon, Netflix, or high-growth startups.*
