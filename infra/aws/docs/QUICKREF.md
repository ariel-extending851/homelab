# LocalStack Testing - Quick Reference

## 🚀 One-Command Test

```bash
# Start LocalStack, run tests, view results
docker run -d -p 4566:4566 localstack/localstack:latest && \
sleep 15 && \
cd /var/mnt/nvme/repos/repos/homelab/infra/aws && \
python3 scripts/validate_localstack.py
```

## 📋 Common Commands

```bash
# Start LocalStack
docker run -d --name localstack -p 4566:4566 localstack/localstack:latest

# Check LocalStack health
curl http://localhost:4566/_localstack/health

# Run automated tests
python3 scripts/validate_localstack.py

# Manual testing
cp provider.localstack.tf.example provider.localstack.tf
terraform init
terraform validate
terraform plan -var-file="terraform.tfvars.localstack"

# Cleanup
rm provider.localstack.tf
rm -f terraform.tfplan terraform-graph.*
docker stop localstack
```

## ✅ Expected Results

- **Tests Passed:** 6/7
- **Resources in Plan:** 13
- **Modules Loaded:** 2 (compute, network)
- **Time:** 2-5 minutes

## 📖 Documentation

| File | Purpose |
|------|---------|
| `LOCALSTACK_TESTING.md` | Complete guide |
| `TESTING_CHECKLIST.md` | Progress tracker |
| `validate_localstack.py` | Automated tests |
| `terraform.tfvars.localstack` | Test variables |
| `provider.localstack.tf.example` | Provider config |

## 🎯 What LocalStack Tests

✅ Terraform syntax
✅ Module structure
✅ Variable validation
✅ Resource dependencies
✅ SOPS integration
✅ Output formatting

## ⚠️ What LocalStack Does NOT Test

❌ EC2 provisioning
❌ Spot instances
❌ k3s installation
❌ Network functionality
❌ IAM permissions

## 🔧 Troubleshooting

```bash
# LocalStack not running
docker start localstack

# Tests fail - provider not configured
cp provider.localstack.tf.example provider.localstack.tf
terraform init -reconfigure

# Module errors
terraform get -update
terraform init

# Clean start
rm -rf .terraform .terraform.lock.hcl provider.localstack.tf
terraform init
```

## 📞 Need Help?

1. Read `LOCALSTACK_TESTING.md` (comprehensive guide)
2. Check `TESTING_CHECKLIST.md` (step-by-step)
3. Review error messages in test output
4. Check LocalStack logs: `docker logs localstack`

---

**Ready?** Run: `python3 scripts/validate_localstack.py`
