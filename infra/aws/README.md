# AWS Infrastructure

Production-ready Terraform configuration for k3s cluster on AWS EC2 Spot Instances.

**Cost:** ~$17.65 USD/month | **Structure:** Modular (compute + network)

---

## 📂 Directory Structure

```
aws/
├── docs/                          # 📚 All documentation
│   ├── README.md                  # Main documentation (you are here)
│   ├── QUICKSTART.md              # 5-minute deployment guide
│   ├── ARCHITECTURE.md            # Architecture details
│   ├── SOPS_SETUP.md              # Secrets management
│   ├── LOCALSTACK_TESTING.md      # Testing guide
│   ├── QUICKREF.md                # Quick reference
│   ├── TESTING_CHECKLIST.md       # Test checklist
│   └── LOCALSTACK_TEST_RESULTS.md # Latest test results
│
├── scripts/                       # 🔧 Utility scripts
│   ├── clean_lab.py               # AWS Nuke cleanup script
│   ├── validate_localstack.py     # LocalStack testing
│   ├── config.yml                 # AWS Nuke configuration
│   └── cost-estimate.csv          # Cost analysis data
│
├── testing/                       # 🧪 LocalStack testing files
│   ├── terraform.tfvars.localstack # LocalStack variables
│   ├── provider.localstack.tf.example # LocalStack provider
│   ├── provider_override.tf       # Active LocalStack override
│   ├── locals_override.tf         # Mock SOPS secrets
│   └── terraform-graph.dot        # Dependency graph
│
├── modules/                       # 🏗️ Terraform modules
│   ├── compute/                   # EC2, IAM, SSH keys
│   │   ├── templates/
│   │   │   └── user_data.tftpl   # k3s installation script
│   │   ├── main.tf
│   │   ├── outputs.tf
│   │   └── variables.tf
│   └── network/                   # VPC, Security Groups
│       ├── main.tf
│       ├── outputs.tf
│       ├── variables.tf
│       └── versions.tf
│
├── main.tf                        # 📄 Root Terraform configuration
├── variables.tf                   # 📄 Root variables
├── outputs.tf                     # 📄 Root outputs
├── terraform.tfvars.sops.yaml    # 🔐 SOPS-encrypted secrets
└── .gitignore                     # 🚫 Git ignore rules
```

---

## 🚀 Quick Start

### 1. Test with LocalStack (Recommended First)
```bash
# Start LocalStack
docker run -d -p 4566:4566 localstack/localstack:latest

# Run tests
python3 scripts/validate_localstack.py
```

**Documentation:** [docs/LOCALSTACK_TESTING.md](docs/LOCALSTACK_TESTING.md)

### 2. Deploy to AWS
```bash
# Configure SOPS secrets
sops terraform.tfvars.sops.yaml

# Deploy
terraform init
terraform plan
terraform apply
```

**Documentation:** [docs/QUICKSTART.md](docs/QUICKSTART.md)

---

## 📚 Documentation

### Getting Started
- **[QUICKSTART.md](docs/QUICKSTART.md)** - 5-minute deployment guide
- **[QUICKREF.md](docs/QUICKREF.md)** - Quick command reference

### Configuration
- **[SOPS_SETUP.md](docs/SOPS_SETUP.md)** - Configure secrets management
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Complete architecture details

### Testing
- **[LOCALSTACK_TESTING.md](docs/LOCALSTACK_TESTING.md)** - LocalStack testing guide
- **[TESTING_CHECKLIST.md](docs/TESTING_CHECKLIST.md)** - Test progress tracker
- **[LOCALSTACK_TEST_RESULTS.md](docs/LOCALSTACK_TEST_RESULTS.md)** - Latest results

---

## 🏗️ Architecture

- **2× EC2 Spot Instances** (t3.small) - Cost optimized
- **k3s** - Lightweight Kubernetes
- **Default VPC** - No NAT Gateway costs
- **SOPS** - Encrypted secrets management

**Cost:** ~$17.65/month
**Savings:** 83% vs EKS+RDS

---

## 🧪 Testing

### Structure Validation (LocalStack)
```bash
python3 scripts/validate_localstack.py
```

Tests: Module structure, variables, dependencies
Time: 5 minutes | Cost: $0

### Behavior Validation (AWS)
```bash
terraform apply
```

Tests: EC2 provisioning, k3s installation, spot behavior
Time: 10 minutes | Cost: ~$17.65/month

---

## 🔐 Security

- ✅ SOPS encryption for secrets
- ✅ IMDSv2 enforced
- ✅ EBS encryption enabled
- ✅ Least privilege IAM roles
- ✅ Security groups with self-referencing

**Setup:** [docs/SOPS_SETUP.md](docs/SOPS_SETUP.md)

---

## 💰 Cost Breakdown

| Component | Monthly Cost |
|-----------|--------------|
| 2× t3.small Spot (730h) | $15.65 |
| 2× EBS gp3 20GB | ~$2.00 |
| **TOTAL** | **~$17.65** |

**Savings vs alternatives:**
- vs On-Demand EC2: 59% cheaper
- vs EKS + RDS: 83% cheaper (~$87/month saved)

---

## 🛠️ Maintenance

### Cleanup AWS Resources
```bash
python3 scripts/clean_lab.py
```

### Update Infrastructure
```bash
terraform plan
terraform apply
```

### Backup Configuration
```bash
# SOPS secrets are already in git (encrypted)
# Backup AGE key separately
cp ~/.config/sops/age/keys.txt /secure/backup/
```

---

## 📞 Support

- **Issues:** Check [docs/LOCALSTACK_TESTING.md](docs/LOCALSTACK_TESTING.md) § Troubleshooting
- **Questions:** Review documentation in `docs/`
- **Updates:** Pull latest changes from repository

---

## 🎯 Status

- ✅ Structure validated (LocalStack)
- ✅ Production-ready code
- ✅ Modular architecture
- ✅ Comprehensive documentation
- ✅ Cost optimized

**Last tested:** 2026-02-04
**Test results:** [docs/LOCALSTACK_TEST_RESULTS.md](docs/LOCALSTACK_TEST_RESULTS.md)

---

**Project:** Lab-DevOps-Pro
**Managed by:** Terraform
**Cloud:** AWS us-east-1
