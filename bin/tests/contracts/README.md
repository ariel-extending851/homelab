# Contract Fixtures

Golden snapshots of real CLI outputs. Feed through the parsing helpers in
`bin/deploy_aws_homelab.py`, `bin/smoke_test.py`, and
`ansible/terraform_inventory_aws.py` to detect schema drift.

## When a tool upgrades

If AWS CLI / Terraform / kubectl / Tailscale changes output schema, the
matching `test_contracts.py` test will fail loudly **before** a production
deploy breaks silently.

## Regenerate

```bash
# After upgrading a CLI tool, capture fresh fixtures and commit:
CAPTURE_CONTRACTS=1 python3 bin/tests/contracts/capture.py
git diff bin/tests/contracts/
# Review the diff, update parsing helpers if schema changed, run tests.
```

## Layout

```
aws_ssm/      describe-instance-information, send-command, get-command-invocation
aws_ec2/      describe-instances (various filters)
terraform/    output -json, output -raw, state list
tailscale/    ip -4, status --json
kubectl/      get applications, get pods, get pvc, get statefulset, jsonpath
```

Each directory has:
- Happy-path fixture(s): typical success case
- Edge-case fixture(s): empty result, pending/not-ready, malformed

## Test-mock divergence warnings

- `bin/smoke_test.py::parse_pvc_rows` treats `parts[1]` as status. Real
  kubectl output (`pvc --no-headers`) has 8 columns where `parts[2]` is
  status. Contract test `test_contract_kubectl_pvc_real_format` verifies
  drift.
- `bin/smoke_test.py::parse_statefulset_rows` treats `parts[1]` and
  `parts[2]` as desired/ready. Real output has columns `(ns, name, "N/M",
  age)`. Same drift detection pattern applies.
