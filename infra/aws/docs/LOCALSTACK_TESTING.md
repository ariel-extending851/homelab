# LocalStack Structure Validation Guide

This guide explains how to test your AWS infrastructure using LocalStack for structure validation.

## 🎯 What LocalStack Testing Covers

### ✅ What You CAN Test

| Component | Test Coverage | Confidence |
|-----------|---------------|------------|
| **Terraform Module Structure** | Full | 100% |
| **Variable Validation** | Full | 100% |
| **Resource Dependencies** | Full | 100% |
| **Module Composition** | Full | 100% |
| **SOPS Integration** | Full | 100% |
| **Output Formatting** | Full | 100% |
| **Provider Configuration** | Full | 100% |
| **Resource Graph** | Full | 100% |

### ❌ What You CANNOT Test

| Component | Reason | Alternative |
|-----------|--------|-------------|
| **EC2 Spot Instances** | Not supported in LocalStack | Use AWS Free Tier |
| **k3s Installation** | No user data execution | Use AWS Free Tier |
| **CloudNativePG Deployment** | No real EC2 instances | Use AWS Free Tier |
| **Network Functionality** | Security groups not enforced | Use AWS Free Tier |
| **IAM Role Assumption** | Limited IAM support | Use AWS Free Tier |

---

## 📋 Prerequisites

### 1. Install LocalStack

#### Option A: Docker (Recommended)

```bash
# Pull LocalStack image
docker pull localstack/localstack:latest

# Start LocalStack
docker run -d \
  --name localstack \
  -p 4566:4566 \
  -e SERVICES=ec2,iam,ssm \
  -e DEBUG=1 \
  localstack/localstack:latest

# Verify LocalStack is running
curl http://localhost:4566/_localstack/health
```

#### Option B: Python pip

```bash
# Install via pip
pip install localstack

# Start LocalStack
localstack start -d

# Verify
localstack status
```

### 2. Install AWS CLI Local (awslocal)

```bash
# Install awslocal wrapper
pip install awscli-local

# Test connection
awslocal ec2 describe-vpcs
```

### 3. Install Required Tools

```bash
# Terraform (if not installed)
brew install terraform  # macOS
# or
sudo apt install terraform  # Linux

# jq (for JSON processing)
brew install jq  # macOS
# or
sudo apt install jq  # Linux

# graphviz (for dependency graphs - optional)
brew install graphviz  # macOS
# or
sudo apt install graphviz  # Linux
```

---

## 🚀 Quick Start

### Step 1: Start LocalStack

```bash
# Start LocalStack container
docker run -d \
  --name localstack \
  -p 4566:4566 \
  localstack/localstack:latest

# Wait for LocalStack to be ready (10-15 seconds)
sleep 15

# Verify health
curl http://localhost:4566/_localstack/health | jq '.services'
```

### Step 2: Configure LocalStack Provider

```bash
cd /var/mnt/nvme/repos/repos/homelab/infra/aws

# Copy LocalStack provider configuration
cp provider.localstack.tf.example provider.localstack.tf
```

### Step 3: Run Automated Tests

```bash
# Execute test script
./test-localstack.sh
```

**Expected Output:**
```
╔═══════════════════════════════════════════════════════════════╗
║     AWS Infrastructure - LocalStack Structure Validation     ║
╚═══════════════════════════════════════════════════════════════╝

[INFO] Checking prerequisites...
[✓] LocalStack is running
[✓] Terraform installed (v1.5.0)
[✓] LocalStack provider configured
[!] SOPS not configured (will use mock secrets)

[INFO] Starting structure validation tests...

[INFO] Test 1/7: Terraform initialization
[✓] Terraform initialized successfully

[INFO] Test 2/7: Configuration validation
[✓] Configuration is valid

[INFO] Test 3/7: Module loading
[✓] Modules loaded successfully
  - Found 2 modules (compute, network)

[INFO] Test 4/7: Variable validation
[✓] Variables validated successfully

[INFO] Test 5/7: Plan generation
[✓] Plan generated successfully
  - Plan includes 13 resource changes

[INFO] Test 6/7: Dependency graph generation
[✓] Dependency graph generated
  - Graph saved to: terraform-graph.dot

[INFO] Test 7/7: Output validation
[!] Outputs not yet available (requires apply)

╔═══════════════════════════════════════════════════════════════╗
║                      Test Summary                             ║
╚═══════════════════════════════════════════════════════════════╝

Tests Passed: 6
Tests Failed: 0

✓ All structure validation tests passed!
```

---

## 📖 Manual Testing Steps

If you prefer to test manually instead of using the automated script:

### Step 1: Initialize Terraform

```bash
cd /var/mnt/nvme/repos/repos/homelab/infra/aws

# Copy LocalStack provider
cp provider.localstack.tf.example provider.localstack.tf

# Initialize
terraform init
```

### Step 2: Validate Configuration

```bash
# Validate Terraform syntax
terraform validate

# Expected output:
# Success! The configuration is valid.
```

### Step 3: Check Module Loading

```bash
# Update modules
terraform get -update

# List modules
terraform providers

# Expected output:
# Providers required by configuration:
# ├── provider[registry.terraform.io/hashicorp/aws] ~> 5.0
# └── provider[registry.terraform.io/carlpett/sops] ~> 0.7.0
```

### Step 4: Generate Plan

```bash
# Generate execution plan
terraform plan -var-file="terraform.tfvars.localstack" -out=terraform.tfplan

# Review plan
terraform show terraform.tfplan
```

**Expected Resources in Plan:**
1. `module.network.aws_security_group.k3s_cluster`
2. `module.k3s_cluster.aws_iam_role.k3s_node`
3. `module.k3s_cluster.aws_iam_role_policy_attachment.k3s_node_ssm`
4. `module.k3s_cluster.aws_iam_instance_profile.k3s_node`
5. `module.k3s_cluster.aws_key_pair.homelab`
6. `module.k3s_cluster.aws_launch_template.k3s_node`
7. `module.k3s_cluster.aws_spot_instance_request.k3s_server`
8. `module.k3s_cluster.aws_spot_instance_request.k3s_agent`
9. `module.k3s_cluster.aws_ec2_tag.k3s_server_name`
10. `module.k3s_cluster.aws_ec2_tag.k3s_agent_name`
11. Data sources (VPC, subnets, AMI)

### Step 5: Generate Dependency Graph

```bash
# Generate DOT format graph
terraform graph > terraform-graph.dot

# Convert to PNG (requires graphviz)
dot -Tpng terraform-graph.dot -o terraform-graph.png

# View graph
open terraform-graph.png  # macOS
# or
xdg-open terraform-graph.png  # Linux
```

### Step 6: Test SOPS Integration (Optional)

If you have SOPS configured:

```bash
# Verify SOPS can decrypt
sops --decrypt terraform.tfvars.sops.yaml

# Verify Terraform can load SOPS secrets
terraform plan -var-file="terraform.tfvars.localstack"

# Check for SOPS errors
grep -i "sops" .terraform/providers/*/terraform-provider-sops*
```

### Step 7: Validate Outputs

```bash
# List expected outputs
terraform output

# Show specific output
terraform output k3s_server_public_ip

# Note: Outputs will be empty until apply is run
```

---

## 🧪 Testing Specific Components

### Test Network Module

```bash
# Plan network module only
terraform plan -target=module.network \
  -var-file="terraform.tfvars.localstack"

# Expected resources:
# - aws_security_group.k3s_cluster
# - data.aws_vpc.default
# - data.aws_subnets.default
```

### Test Compute Module

```bash
# Plan compute module only
terraform plan -target=module.k3s_cluster \
  -var-file="terraform.tfvars.localstack"

# Expected resources:
# - aws_iam_role.k3s_node
# - aws_key_pair.homelab
# - aws_spot_instance_request.k3s_server
# - aws_spot_instance_request.k3s_agent
# - etc.
```

### Test Variable Validation

```bash
# Test invalid instance type
terraform plan -var="instance_type=t2.large" \
  -var-file="terraform.tfvars.localstack"

# Expected error:
# Error: Invalid value for variable
# Instance type must be t3.micro, t3.small, or t3.medium

# Test invalid EBS size
terraform plan -var="ebs_volume_size=150" \
  -var-file="terraform.tfvars.localstack"

# Expected error:
# Error: Invalid value for variable
# EBS volume size must be between 20GB and 100GB
```

### Test SOPS Secret Loading

```bash
# Verify SOPS secrets are loaded
terraform console -var-file="terraform.tfvars.localstack"

# In console, test:
> local.secrets["ssh_public_key"]
> local.secrets["k3s_token"]

# Exit console
> exit
```

---

## 🔍 Interpreting Results

### Success Indicators ✅

- All tests pass in `test-localstack.sh`
- `terraform plan` generates 13 resource changes
- No validation errors in modules
- Dependency graph generates without errors
- SOPS secrets decrypt successfully

### Expected Warnings ⚠️

These are **normal** for LocalStack:

```
Warning: Value for undeclared variable
Warning: Experimental feature "module_variable_optional_attrs" is active
Warning: AWS account ID not available
```

### Failure Indicators ❌

These indicate **real problems**:

```
Error: Invalid resource type
Error: Unsupported argument
Error: Invalid value for variable
Error: Module not installed
Error: Failed to load plugin schemas
```

---

## 📊 Understanding Limitations

### What LocalStack Does

LocalStack creates **metadata** for AWS resources but doesn't actually provision them:

```bash
# After terraform apply
awslocal ec2 describe-instances

# Returns: Instance metadata (ID, type, state)
# But: No actual EC2 instance running
```

### Spot Instance Behavior

Your Terraform uses spot instances, but LocalStack:

❌ **Does NOT emulate:**
- Spot market pricing
- Spot interruption notices
- Spot bid acceptance/rejection
- Persistent spot requests

✅ **Does emulate:**
- Instance request creation (metadata only)
- Instance tagging
- Instance state (mock)

### User Data Execution

LocalStack does NOT execute user data scripts:

❌ **Will NOT happen:**
- k3s installation
- CloudNativePG operator deployment
- System updates
- Kernel module configuration

✅ **Will happen:**
- User data stored in instance metadata
- User data accessible via API
- User data can be inspected

---

## 🛠️ Troubleshooting

### Issue: LocalStack Not Running

**Symptom:**
```
[✗] LocalStack is not running on localhost:4566
```

**Solution:**
```bash
# Check if LocalStack container exists
docker ps -a | grep localstack

# Start existing container
docker start localstack

# Or create new container
docker run -d -p 4566:4566 localstack/localstack:latest
```

### Issue: Terraform Init Fails

**Symptom:**
```
Error: Failed to query available provider packages
```

**Solution:**
```bash
# Remove .terraform directory
rm -rf .terraform .terraform.lock.hcl

# Re-initialize
terraform init
```

### Issue: SOPS Decryption Fails

**Symptom:**
```
Error: Failed to get file: failed to decrypt
```

**Solution:**
```bash
# Check SOPS configuration
echo $SOPS_AGE_KEY_FILE

# Verify AGE key exists
ls -la $SOPS_AGE_KEY_FILE

# Test SOPS manually
sops --decrypt terraform.tfvars.sops.yaml

# If not configured, use mock secrets
# Edit provider.localstack.tf and uncomment mock secrets section
```

### Issue: Module Not Found

**Symptom:**
```
Error: Module not installed
```

**Solution:**
```bash
# Get modules
terraform get -update

# Re-initialize
terraform init
```

### Issue: Invalid Provider Configuration

**Symptom:**
```
Error: Unsupported provider configuration
```

**Solution:**
```bash
# Ensure provider.localstack.tf exists
ls -la provider.localstack.tf

# If not, create it
cp provider.localstack.tf.example provider.localstack.tf

# Re-initialize with reconfigure
terraform init -reconfigure
```

---

## 🧹 Cleanup

### After Testing

```bash
# Remove LocalStack provider config
rm provider.localstack.tf

# Remove test artifacts
rm -f terraform.tfplan
rm -f terraform-graph.dot
rm -f terraform-graph.png
rm -rf .terraform

# Stop LocalStack
docker stop localstack

# Remove LocalStack container (optional)
docker rm localstack
```

### Reset to Production Configuration

```bash
# Re-initialize with production provider
terraform init -reconfigure

# Verify production provider
terraform providers
```

---

## 📈 Next Steps After LocalStack Validation

Once structure validation passes:

### Option A: Deploy to AWS Free Tier

```bash
# Configure AWS credentials
aws configure

# Use production variables
terraform plan

# Deploy
terraform apply
```

### Option B: Skip to Production

```bash
# If confident in structure validation
# Deploy directly to production AWS account

# Review cost estimate
terraform plan

# Deploy with cost monitoring
terraform apply
```

### Option C: Implement Additional Tests

```bash
# Add Terratest (Go-based testing)
# Add terraform-compliance (policy testing)
# Add checkov (security scanning)
```

---

## 📚 Additional Resources

- [LocalStack Documentation](https://docs.localstack.cloud/)
- [Terraform Testing Best Practices](https://www.terraform.io/docs/testing/)
- [AWS Provider Documentation](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
- [SOPS Documentation](https://github.com/mozilla/sops)

---

## 🎯 Testing Checklist

Use this checklist to track your validation:

- [ ] LocalStack installed and running
- [ ] `provider.localstack.tf` configured
- [ ] `terraform init` succeeds
- [ ] `terraform validate` passes
- [ ] Modules load correctly (compute, network)
- [ ] Variables validate with test values
- [ ] `terraform plan` generates 13 resources
- [ ] Dependency graph generates
- [ ] SOPS integration tested (if applicable)
- [ ] All automated tests pass
- [ ] Documentation reviewed
- [ ] Ready for AWS deployment

---

**Status:** Ready for structure validation testing
**Last Updated:** 2026-02-04
**Maintainer:** Tech Lead
