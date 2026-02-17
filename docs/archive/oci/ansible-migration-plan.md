---
DEPRECATED: This document refers to an old architecture based on Oracle Cloud Infrastructure (OCI) and is kept for historical purposes only. The current architecture runs on AWS.
---

# Ansible Migration Plan

## Executive Summary

**Objective:** Migrate all infrastructure scripts from `scripts/` and `infra/aws/scripts/` into a unified Ansible automation framework.

**Current Status:** Ansible is **partially operational** - it can deploy k3s but lacks application deployment, monitoring, and operational playbooks.

**Timeline:** 1-2 days of work

---

## Current State Analysis

### ✅ Ansible Works
- Basic k3s server/agent deployment
- Terraform dynamic inventory (AWS + OCI versions)
- Role structure for k3s installation

### ❌ Missing/Needs Improvement
- No application deployment (***, ***, etc.)
- No monitoring setup (Grafana, Prometheus)
- No operational playbooks (backup, recovery, maintenance)
- No RPi-specific optimizations
- No Tailscale integration
- No secret management (SOPS)

---

## Scripts to Migrate

### 1. Emergency/Recovery Scripts
**Source:** `scripts/emergency-recovery.sh`
**Migrate to:** `ansible/playbooks/recovery/` with role `emergency_recovery`
**Priority:** HIGH
**Tasks:**
- Fix Tailscale proxy StatefulSets
- Verify pod distribution
- Test endpoint accessibility
- Generate recovery reports

### 2. RPi Optimization Scripts
**Source:** `scripts/optimize-rpi4-swap.sh`
**Migrate to:** `ansible/roles/rpi_optimization/`
**Priority:** HIGH
**Tasks:**
- Configure swap on RPi 3 and 4
- Optimize memory settings
- Tune containerd for ARM
- Set up log rotation

### 3. Application Management Scripts
**Source:**
- `scripts/***-config-manager.sh`
- `scripts/***-vpn-repair.sh`
**Migrate to:** `ansible/roles/media_apps/tasks/`
**Priority:** MEDIUM
**Tasks:**
- Manage *** configuration
- VPN connection repair automation
- Category management
- Health checks

### 4. Infrastructure Scripts
**Source:** `infra/aws/scripts/`
**Migrate to:** `ansible/playbooks/infrastructure/`
**Priority:** MEDIUM
**Tasks:**
- `clean-lab.sh` → Cleanup playbook
- `test-localstack.sh` → Testing role
- Cost estimation → Reporting role

### 5. Migration Scripts
**Source:**
- `scripts/migrate-proxies.sh`
- `scripts/rollback-proxy-migration.sh`
**Migrate to:** `ansible/playbooks/maintenance/`
**Priority:** LOW
**Tasks:**
- Proxy migration automation
- Rollback capabilities

---

## Proposed Ansible Structure

```
ansible/
├── ansible.cfg                          # Ansible configuration
├── inventory/
│   ├── production.yml                   # Static inventory for RPi nodes
│   ├── aws_ec2.yml                      # AWS dynamic inventory
│   └── group_vars/
│       ├── all.yml                      # Common variables
│       ├── k3s_server.yml               # Control plane vars
│       ├── k3s_agent.yml                # Worker node vars
│       └── raspberry_pi.yml             # RPi-specific vars
├── playbooks/
│   ├── site.yml                         # Main site playbook
│   ├── deploy_k3s.yml                   # Existing k3s deployment
│   ├── deploy_apps.yml                  # Application deployment
│   ├── setup_monitoring.yml             # Monitoring stack
│   ├── recovery/
│   │   ├── emergency_recovery.yml       # From emergency-recovery.sh
│   │   └── cluster_health_check.yml
│   ├── maintenance/
│   │   ├── cleanup.yml                  # From clean-lab.sh
│   │   ├── optimize_rpi.yml             # From optimize-rpi4-swap.sh
│   │   └── backup_configs.yml
│   └── infrastructure/
│       ├── test_localstack.yml          # From test-localstack.sh
│       └── cost_report.yml
├── roles/
│   ├── common/                          # Base setup for all nodes
│   │   ├── tasks/
│   │   │   └── main.yml
│   │   └── handlers/
│   │       └── main.yml
│   ├── k3s/                             # Existing k3s role (enhance)
│   │   └── ...
│   ├── tailscale/                       # NEW: Tailscale setup
│   │   ├── tasks/
│   │   │   └── main.yml
│   │   └── templates/
│   │       └── tailscale-up.sh.j2
│   ├── media_apps/                      # NEW: Media stack
│   │   ├── tasks/
│   │   │   ├── main.yml
│   │   │   ├── ***.yml
│   │   │   ├── ***.yml
│   │   │   ├── ***.yml
│   │   │   ├── ***.yml
│   │   │   └── ***.yml
│   │   ├── templates/
│   │   │   └── *.yaml.j2
│   │   └── vars/
│   │       └── main.yml
│   ├── monitoring/                      # NEW: Prometheus/Grafana
│   │   ├── tasks/
│   │   │   └── main.yml
│   │   └── templates/
│   │       └── *.yaml.j2
│   ├── rpi_optimization/                # NEW: From optimize-rpi4-swap.sh
│   │   ├── tasks/
│   │   │   └── main.yml
│   │   └── templates/
│   │       └── sysctl.conf.j2
│   └── emergency_recovery/              # NEW: From emergency-recovery.sh
│       ├── tasks/
│       │   └── main.yml
│       └── files/
│           └── recovery_checks.sh
└── scripts/                             # Helper scripts
    ├── inventory_aws.py                 # Current terraform_inventory_aws.py
    └── inventory_oci.py                 # Current terraform_inventory.py
```

---

## Implementation Plan

### Phase 1: Foundation (Day 1 Morning)
**Goal:** Get Ansible fully operational with proper inventory

1. **Update inventory structure**
   - Create `inventory/production.yml` with RPi nodes
   - Add Tailscale IP support to dynamic inventory
   - Set up group variables

2. **Enhance existing k3s role**
   - Add Tailscale integration
   - Support for new server IP discovery
   - Better token management

3. **Create common role**
   - Base packages installation
   - SSH key setup
   - Log rotation configuration

### Phase 2: Critical Operations (Day 1 Afternoon)
**Goal:** Migrate recovery and optimization scripts

1. **Create emergency_recovery role**
   - Convert `emergency-recovery.sh` to Ansible tasks
   - Add pre-flight checks
   - Create health check tasks

2. **Create rpi_optimization role**
   - Convert `optimize-rpi4-swap.sh`
   - Add memory tuning
   - Configure containerd for ARM

3. **Create recovery playbooks**
   - `emergency_recovery.yml`
   - `cluster_health_check.yml`

### Phase 3: Application Deployment (Day 2 Morning)
**Goal:** Automate media stack deployment

1. **Create media_apps role**
   - PVC creation tasks
   - Application deployment tasks
   - Configuration management

2. **Create deploy_apps playbook**
   - Deploy all media applications
   - Set up Tailscale ingresses
   - Verify endpoints

### Phase 4: Monitoring & Maintenance (Day 2 Afternoon)
**Goal:** Complete monitoring and maintenance automation

1. **Create monitoring role**
   - Prometheus deployment
   - Grafana deployment
   - ServiceMonitor setup

2. **Create maintenance playbooks**
   - Cleanup playbook
   - Backup playbook
   - Testing playbook

---

## Priority Questions for You

1. **Tailscale Integration:**
   - Should Ansible manage Tailscale authentication?
   - Do you have OAuth client credentials for automated setup?

2. **Secret Management:**
   - Should we integrate SOPS with Ansible?
   - Or use Ansible Vault for secrets?

3. **AWS Credentials:**
   - How should Ansible authenticate with AWS for the dynamic inventory?
   - Environment variables? AWS profile? IAM role?

4. **Application Configuration:**
   - Do you want Ansible to manage app configs (***/*** settings)?
   - Or just deploy the pods and let you configure via UI?

5. **Backup Strategy:**
   - Should we add automated backup playbooks for:
     - Kubernetes manifests
     - Application configurations
     - Persistent volumes?

---

## Quick Start Commands (After Migration)

```bash
# Deploy everything
ansible-playbook -i inventory/production.yml playbooks/site.yml

# Just deploy k3s
ansible-playbook -i inventory/production.yml playbooks/deploy_k3s.yml

# Deploy applications
ansible-playbook -i inventory/production.yml playbooks/deploy_apps.yml

# Emergency recovery
ansible-playbook -i inventory/production.yml playbooks/recovery/emergency_recovery.yml

# Optimize RPi nodes
ansible-playbook -i inventory/production.yml playbooks/maintenance/optimize_rpi.yml -l raspberry_pi

# Health check
ansible-playbook -i inventory/production.yml playbooks/recovery/cluster_health_check.yml

# Check cluster status
ansible-playbook -i inventory/production.yml playbooks/recovery/cluster_health_check.yml --check
```

---

## Cost/Benefit Analysis

**Current State (Scripts):**
- ❌ Manual execution required
- ❌ No idempotency (running twice = problems)
- ❌ Hardcoded values
- ❌ No error handling
- ✅ Quick to write

**Future State (Ansible):**
- ✅ Fully automated
- ✅ Idempotent (run multiple times safely)
- ✅ Variable-driven configuration
- ✅ Built-in error handling and retries
- ✅ Rollback capabilities
- ✅ Documentation as code
- ⚠️ Initial setup time required

**Recommendation:** Proceed with migration. The long-term maintainability and reliability benefits far outweigh the initial setup effort.

---

## Next Steps

**Ready to proceed? Please answer the 5 priority questions above, and I'll start implementing Phase 1.**

Alternatively, if you want to focus on specific areas first, let me know which scripts are most important to migrate immediately.
