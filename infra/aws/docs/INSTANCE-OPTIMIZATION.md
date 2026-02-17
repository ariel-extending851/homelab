# Instance Optimization & Automated Scheduling

## Overview

This document describes the instance optimization and automated scheduling implementation for the k3s homelab infrastructure.

## Changes Summary

### Instance Type Upgrade
- **k3s-server-1 (control plane):** t3.small (2GB) → **t3.medium (4GB)**
- **k3s-agent-2 (worker):** t3.small (2GB) - **no change**

**Rationale:** The control plane was experiencing memory exhaustion with only 2GB RAM, causing API server freezes and cluster instability.

### Workload Redistribution

**Before:**
```
k3s-server-1 (2GB):  Control plane + Prometheus + Grafana = ~1.4GB (70% RAM)
k3s-agent-2 (2GB):   Loki + Searxng = ~1.2GB (60% RAM)
```

**After:**
```
k3s-server-1 (4GB):  Control plane only = ~500MB (12.5% RAM) ✅
k3s-agent-2 (2GB):   Prometheus + Grafana + Loki + Searxng = ~1.8GB (90% RAM) ⚠️
```

**Changes Made:**
- Moved `Grafana` from k3s-server-1 → k3s-agent-2
- Moved `Prometheus` from k3s-server-1 → k3s-agent-2
- Media stack remains on rasp-pi-04 (unchanged)

### Automated Scheduling

**Lambda-based instance scheduler:**
- **Schedule:** 10 AM - 9 PM BRT (Brazil timezone) daily
- **Uptime:** 11 hours/day = 45.2% monthly uptime
- **Control:** Manual override via Lambda Function URL

**Architecture:**
```
EventBridge Rules
├── Start Rule (cron: 0 13 * * ? *)  → 10 AM BRT = 1 PM UTC
└── Stop Rule (cron: 0 0 * * ? *)    → 9 PM BRT = 12 AM UTC
           ↓
    Lambda Function
    (hl-ec2-scheduler)
           ↓
    EC2 API (Start/Stop)
```

## Cost Analysis

### Monthly Costs

| Configuration | Monthly Cost | Notes |
|---------------|-------------|-------|
| **Previous (broken)** | $30.36 | 2× t3.small 24/7 |
| **New (with scheduling)** | **$24.59** | t3.medium + t3.small, 45% uptime |
| **New (without scheduling)** | $45.55 | t3.medium + t3.small, 24/7 |

**Breakdown (with scheduling):**
```
Compute (45% uptime):
  k3s-server-1 (t3.medium): $0.0416/hr × 330 hrs = $13.73
  k3s-agent-2 (t3.small):   $0.0208/hr × 330 hrs = $6.83

Storage (always charged):
  EBS volumes: ~$4.00

Total: $24.59/month
Savings vs previous: -$5.77/month (-19%)
```

## Manual Control

The Lambda function uses IAM authentication. Use the AWS CLI to invoke it:

### Start Instances Early
```bash
cd infra/aws
$(terraform output -raw manual_start_command)
```

### Stop Instances Early
```bash
cd infra/aws
$(terraform output -raw manual_stop_command)
```

### Check Status
```bash
cd infra/aws
$(terraform output -raw manual_status_command)
```

**Note:** These commands require AWS credentials with permission to invoke the Lambda function.

## Services Running 24/7

These services run on Raspberry Pi hardware (no AWS cost):
- ✅ AdGuard DNS (rasp-pi-03)
- ✅ ***, ***, *** (rasp-pi-04)
- ✅ *** + VPN (rasp-pi-04)
- ✅ *** (rasp-pi-04)

## Services That Stop at Night

These services run on AWS instances (scheduled):
- ⏹️ k3s control plane (k3s-server-1)
- ⏹️ Prometheus, Grafana, Loki (k3s-agent-2)
- ⏹️ Searxng (k3s-agent-2)

## Deployment Instructions

### 1. Review Changes
```bash
cd infra/aws
terraform plan
```

### 2. Apply Infrastructure
```bash
terraform apply
```

**Expected changes:**
- Modify launch templates for new instance types
- Create Lambda function and IAM role
- Create EventBridge schedules
- No downtime for rasp-pi services

### 3. Verify Scheduler
```bash
# Check Lambda function
aws lambda list-functions --query "Functions[?FunctionName=='hl-ec2-scheduler']"

# Check EventBridge rules
aws events list-rules --name-prefix "hl-k3s-"
```

### 4. Apply Kubernetes Changes
```bash
# ArgoCD will auto-sync changes from develop branch
kubectl get pods -n grafana -w
kubectl get pods -n prometheus -w

# Verify new node placement
kubectl get pods -A -o wide | grep -E "(grafana|prometheus)"
```

## Rollback Procedures

### Revert Instance Types
```bash
cd infra/aws

# Edit terraform.tfvars or use CLI override
terraform apply \
  -var="server_instance_type=t3.small" \
  -var="agent_instance_type=t3.small"
```

### Disable Scheduling
```bash
terraform apply -var="enable_scheduling=false"
```

### Revert Workload Placement
```bash
cd ../../k8s/apps

# Revert Git changes
git revert <commit-hash>
git push origin develop
```

## Monitoring & Troubleshooting

### Check Instance States
```bash
aws ec2 describe-instances \
  --instance-ids i-07f1cf6f322c8aa3c \
  --query 'Reservations[0].Instances[0].[InstanceType,State.Name]' \
  --output table
```

### View Lambda Logs
```bash
aws logs tail /aws/lambda/hl-ec2-scheduler --follow
```

### Test Manual Start/Stop
```bash
# Get commands from Terraform output
terraform output manual_start_command
terraform output manual_stop_command
```

## Security Considerations

✅ **Lambda Function Authentication:** The Lambda function URL uses `authorization_type = "AWS_IAM"`, which requires callers to sign requests with AWS SigV4. This prevents unauthenticated access.

**To invoke the function, you must:**
1. Use the AWS CLI: `aws lambda invoke ...`
2. Or use a tool that supports AWS SigV4 signing (e.g., `awscurl`)
3. Have IAM permissions to invoke the Lambda function

**Additional recommendations:**
1. **Rate limiting:** Consider adding CloudFront + WAF in front of the Lambda URL
2. **IP allowlisting:** Lambda URLs bypass security groups; use WAF for IP filtering if needed
3. **Least privilege:** The Lambda IAM role is scoped to specific EC2 instance ARNs

**Current security posture:**
- Lambda requires IAM-authenticated requests (no anonymous access)
- IAM permissions are scoped to specific EC2 instances (not wildcard)
- Instance IDs are passed via environment variables (not hardcoded in code)
- Worst case: Compromised credentials can only start/stop instances (no data access)

## References

- [AWS Lambda Pricing](https://aws.amazon.com/lambda/pricing/)
- [EventBridge Pricing](https://aws.amazon.com/eventbridge/pricing/)
- [EC2 Pricing Calculator](https://calculator.aws/#/)
- [Terraform AWS Provider Docs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
