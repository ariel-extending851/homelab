# LocalStack Testing Checklist

Use this checklist to track your LocalStack structure validation progress.

## 📋 Pre-Testing Setup

### Prerequisites
- [ ] Docker installed and running
- [ ] Terraform >= 1.5.0 installed
- [ ] jq installed (for JSON processing)
- [ ] LocalStack student subscription active

### LocalStack Installation
- [ ] LocalStack container pulled: `docker pull localstack/localstack:latest`
- [ ] LocalStack started: `docker run -d -p 4566:4566 localstack/localstack:latest`
- [ ] LocalStack health check passes: `curl http://localhost:4566/_localstack/health`
- [ ] awslocal CLI installed (optional): `pip install awscli-local`

### Repository Setup
- [ ] Navigated to: `/var/mnt/nvme/repos/repos/homelab/infra/aws`
- [ ] All testing files present:
  - [ ] `terraform.tfvars.localstack`
  - [ ] `provider.localstack.tf.example`
  - [ ] `test-localstack.sh`
  - [ ] `LOCALSTACK_TESTING.md`

---

## 🚀 Automated Testing (Recommended)

### Quick Test
- [ ] Make test script executable: `chmod +x test-localstack.sh`
- [ ] Run automated tests: `./test-localstack.sh`
- [ ] All tests pass (6/7 expected to pass)
- [ ] Review test output for warnings

### Expected Results
- [ ] Test 1/7: Terraform initialization ✓
- [ ] Test 2/7: Configuration validation ✓
- [ ] Test 3/7: Module loading ✓
- [ ] Test 4/7: Variable validation ✓
- [ ] Test 5/7: Plan generation ✓
- [ ] Test 6/7: Dependency graph generation ✓
- [ ] Test 7/7: Output validation (may warn - OK)

---

## 🔧 Manual Testing (Optional)

### Step 1: Provider Configuration
- [ ] Copy LocalStack provider: `cp provider.localstack.tf.example provider.localstack.tf`
- [ ] Verify provider file created: `ls -la provider.localstack.tf`

### Step 2: Terraform Initialization
- [ ] Run: `terraform init`
- [ ] Check: Providers downloaded (aws, sops)
- [ ] Check: Modules initialized (compute, network)
- [ ] Check: No errors displayed

### Step 3: Configuration Validation
- [ ] Run: `terraform validate`
- [ ] Expected output: "Success! The configuration is valid."
- [ ] No syntax errors
- [ ] No module errors

### Step 4: Variable Validation
- [ ] Run: `terraform validate -var-file="terraform.tfvars.localstack"`
- [ ] Variables load correctly
- [ ] Type validation passes
- [ ] Constraint validation passes

### Step 5: Module Loading
- [ ] Run: `terraform get -update`
- [ ] Compute module loads
- [ ] Network module loads
- [ ] No module errors

### Step 6: Plan Generation
- [ ] Run: `terraform plan -var-file="terraform.tfvars.localstack" -out=terraform.tfplan`
- [ ] Plan generates successfully
- [ ] Count resources: Should show 13 resources
- [ ] Review plan for unexpected changes

### Step 7: Dependency Graph
- [ ] Run: `terraform graph > terraform-graph.dot`
- [ ] Graph file created
- [ ] No circular dependencies
- [ ] (Optional) Convert to PNG: `dot -Tpng terraform-graph.dot -o terraform-graph.png`

### Step 8: SOPS Integration (If Configured)
- [ ] SOPS_AGE_KEY_FILE set: `echo $SOPS_AGE_KEY_FILE`
- [ ] AGE key exists: `ls -la $SOPS_AGE_KEY_FILE`
- [ ] SOPS decrypts: `sops --decrypt terraform.tfvars.sops.yaml`
- [ ] Terraform loads secrets: Check plan output

---

## 🔍 Validation Checks

### Module Structure
- [ ] `modules/compute/` exists
- [ ] `modules/network/` exists
- [ ] `modules/compute/templates/` exists
- [ ] `modules/compute/templates/user_data.tftpl` exists
- [ ] All module files have correct structure

### Resource Count
- [ ] Plan shows 13 total resources:
  - [ ] 1× Security group (network module)
  - [ ] 1× IAM role (compute module)
  - [ ] 1× IAM policy attachment (compute module)
  - [ ] 1× IAM instance profile (compute module)
  - [ ] 1× SSH key pair (compute module)
  - [ ] 1× Launch template (compute module)
  - [ ] 2× Spot instance requests (compute module)
  - [ ] 2× EC2 tags (compute module)
  - [ ] 3× Data sources (VPC, subnets, AMI)

### Variable Validation
- [ ] `instance_type` validates (t3.micro, t3.small, t3.medium only)
- [ ] `ebs_volume_size` validates (20-100 GB range)
- [ ] `k3s_version` validates (vX.Y.Z+k3sN format)
- [ ] `ssh_allowed_cidr` validates (at least one CIDR)
- [ ] `k3s_api_allowed_cidr` validates (at least one CIDR)

### Output Structure
- [ ] `k3s_server_public_ip` defined
- [ ] `k3s_server_private_ip` defined
- [ ] `k3s_agent_public_ip` defined
- [ ] `k3s_agent_private_ip` defined
- [ ] `ssh_command_server` formatted correctly
- [ ] `ssh_command_agent` formatted correctly
- [ ] `kubeconfig_command` formatted correctly

---

## 🎯 Success Criteria

### Must Pass ✅
- [ ] All automated tests pass (6/7)
- [ ] No Terraform syntax errors
- [ ] No module loading errors
- [ ] No variable validation errors
- [ ] Plan generates with 13 resources
- [ ] Dependency graph generates without cycles

### Should Pass ✅
- [ ] SOPS secrets decrypt (if configured)
- [ ] No unexpected warnings
- [ ] Module composition correct
- [ ] Resource dependencies correct

### May Warn ⚠️
These warnings are **normal** for LocalStack:
- [ ] "AWS account ID not available"
- [ ] "Experimental feature active"
- [ ] "Value for undeclared variable"
- [ ] Outputs not available (requires apply)

---

## ❌ Known Limitations

### Expected Limitations (Not Errors)
- [ ] Understood: Spot instances won't actually provision
- [ ] Understood: User data (k3s) won't execute
- [ ] Understood: Security groups created but not enforced
- [ ] Understood: IAM roles created but not functional
- [ ] Understood: No actual EC2 instances boot
- [ ] Understood: CloudNativePG operator won't deploy

### These Are NOT Structure Issues
If you see these, it's **expected** - LocalStack cannot test:
- Spot market behavior
- EC2 instance booting
- k3s installation
- Network traffic filtering
- IAM permission enforcement

---

## 🧹 Post-Testing Cleanup

### After Successful Validation
- [ ] Review `terraform.tfplan` for correctness
- [ ] Review `terraform-graph.dot` for dependencies
- [ ] Document any issues found
- [ ] Remove LocalStack provider: `rm provider.localstack.tf`
- [ ] Clean test artifacts: `rm -f terraform.tfplan terraform-graph.*`

### Prepare for AWS Deployment
- [ ] LocalStack validation complete
- [ ] All structure tests pass
- [ ] Ready to configure SOPS secrets
- [ ] Ready to deploy to AWS

### LocalStack Cleanup (Optional)
- [ ] Stop LocalStack: `docker stop localstack`
- [ ] Remove container: `docker rm localstack`
- [ ] Remove image (optional): `docker rmi localstack/localstack:latest`

---

## 🆘 Troubleshooting

### If Tests Fail

#### LocalStack Not Running
- [ ] Check: `docker ps | grep localstack`
- [ ] Start: `docker start localstack`
- [ ] Wait 10-15 seconds for initialization
- [ ] Retry tests

#### Terraform Init Fails
- [ ] Remove: `rm -rf .terraform .terraform.lock.hcl`
- [ ] Verify: `provider.localstack.tf` exists
- [ ] Re-initialize: `terraform init`

#### Module Not Found
- [ ] Check modules exist: `ls -la modules/`
- [ ] Update modules: `terraform get -update`
- [ ] Re-initialize: `terraform init`

#### SOPS Errors
- [ ] Option A: Configure SOPS properly
- [ ] Option B: Comment out SOPS in `provider.localstack.tf`
- [ ] Option C: Use mock secrets (see provider file)

#### Provider Configuration Errors
- [ ] Verify: `provider.localstack.tf` exists
- [ ] Check endpoints: Should point to `localhost:4566`
- [ ] Re-initialize: `terraform init -reconfigure`

### If You Need Help
- [ ] Review: `LOCALSTACK_TESTING.md`
- [ ] Check: LocalStack logs: `docker logs localstack`
- [ ] Check: Terraform debug: `TF_LOG=DEBUG terraform plan`

---

## 📊 Testing Metrics

Track your testing progress:

**Testing Date:** _______________

**LocalStack Version:** _______________

**Terraform Version:** _______________

**Test Results:**
- Tests Passed: _____ / 7
- Resources in Plan: _____ (expected: 13)
- Modules Loaded: _____ (expected: 2)
- Warnings: _____ (describe below)
- Errors: _____ (describe below)

**Issues Found:**
```
(Note any issues here)
```

**Resolution:**
```
(Note how issues were resolved)
```

**Time Spent:**
- Setup: _____ minutes
- Testing: _____ minutes
- Troubleshooting: _____ minutes
- Total: _____ minutes

**Ready for AWS Deployment?** YES / NO

---

## 🎓 Understanding What Was Tested

### Structure Validation ✅
You validated that your Terraform code:
- Compiles without syntax errors
- Has correct module structure
- Has valid variable definitions
- Has correct resource dependencies
- Has proper output definitions
- Loads secrets correctly (SOPS)

### What This Means
- Your **code structure** is correct
- Your **module composition** is correct
- Your **variable validation** works
- Your **SOPS integration** works
- You're ready to test **behavior** in AWS

### What Was NOT Tested
- EC2 instances won't boot in LocalStack
- k3s installation won't happen
- CloudNativePG won't deploy
- Spot instances won't provision
- Security groups won't enforce rules

### Next Step
After structure validation passes:
→ Deploy to AWS to test actual behavior
→ See QUICKSTART.md for deployment guide

---

## ✅ Final Checklist

Before moving to AWS deployment:

- [ ] All LocalStack tests pass
- [ ] No structure errors in Terraform code
- [ ] Modules load correctly
- [ ] Variables validate
- [ ] Dependencies are correct
- [ ] SOPS integration tested (if using)
- [ ] Documentation reviewed
- [ ] Understood LocalStack limitations
- [ ] Ready to configure AWS credentials
- [ ] Ready to configure SOPS secrets
- [ ] Ready to deploy to AWS

**Status:** READY / NOT READY

**Notes:**
```
(Add any final notes here)
```

---

**Congratulations!** 🎉

If all items are checked, your Terraform infrastructure structure is validated and you're ready to deploy to AWS!

**Next Steps:**
1. Review SOPS_SETUP.md (configure secrets)
2. Review QUICKSTART.md (AWS deployment)
3. Deploy to AWS and test actual behavior
