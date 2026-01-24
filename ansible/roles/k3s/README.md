# Ansible Role: k3s

Installs and configures [k3s](https://k3s.io/) (Lightweight Kubernetes) on ARM64 architecture for hybrid cloud environments (Oracle Cloud + Raspberry Pi).

## Description

This role automates the deployment of k3s clusters in a hybrid architecture, with support for:

- **Control Plane (Server)**: Single or multi-node k3s server installation
- **Worker Nodes (Agents)**: Scalable agent node deployment
- **ARM64 Optimization**: Tailored for Oracle Cloud ARM instances and Raspberry Pi devices
- **Tailscale Integration**: Automatic mesh networking configuration
- **Resource Awareness**: Optimizations for constrained environments (Raspberry Pi)

## Requirements

- **Architecture**: ARM64 (aarch64) only
- **Minimum RAM**: 512MB (4GB+ recommended for server nodes)
- **OS**: Ubuntu 20.04+, Debian 11+, or Fedora 38+
- **Network**: Internet access for k3s installation script
- **Optional**: Tailscale installed and configured (when `k3s_use_tailscale: true`)

## Role Variables

### Core Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `k3s_version` | `v1.28.5+k3s1` | k3s version to install |
| `k3s_channel` | `stable` | Release channel (stable, latest, or specific version) |
| `k3s_control_node` | `false` | Designate as server/control plane node |

### Server Configuration (`k3s_server_config`)

```yaml
k3s_server_config:
  write-kubeconfig-mode: "0644"
  cluster-cidr: "10.42.0.0/16"
  service-cidr: "10.43.0.0/16"
  disable:
    - traefik  # Disable built-in Traefik
  flannel-backend: "vxlan"
  disable-cloud-controller: true
```

### Agent Configuration (`k3s_agent_config`)

```yaml
k3s_agent_config:
  node-label: []  # e.g., ["workload-type=batch", "gpu=nvidia"]
  node-taint: []  # e.g., ["dedicated=gpu:NoSchedule"]
```

### Tailscale Integration

| Variable | Default | Description |
|----------|---------|-------------|
| `k3s_use_tailscale` | `true` | Use Tailscale IPs for cluster communication |
| `k3s_advertise_on_tailscale` | `true` | Advertise k3s API server on Tailscale network |

### Raspberry Pi Optimizations

| Variable | Default | Description |
|----------|---------|-------------|
| `k3s_pi_optimizations` | `true` | Enable resource-constrained optimizations |
| `k3s_pi_max_pods` | `50` | Max pods per node for Pi devices |

### Backup & High Availability

| Variable | Default | Description |
|----------|---------|-------------|
| `k3s_enable_etcd_snapshots` | `true` | Enable automatic etcd snapshots |
| `k3s_etcd_snapshot_schedule` | `0 */12 * * *` | Cron schedule for snapshots (every 12h) |
| `k3s_etcd_snapshot_retention` | `5` | Number of snapshots to retain |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `k3s_protect_kernel_defaults` | `false` | Enforce kernel security defaults (CIS benchmark) |
| `k3s_secrets_encryption` | `false` | Enable encryption at rest for secrets |

## Dependencies

None. This role is self-contained.

## Example Playbook

### Basic Server + Agent Setup

```yaml
---
- name: Deploy k3s cluster
  hosts: all
  become: true
  roles:
    - role: k3s
      vars:
        k3s_control_node: "{{ inventory_hostname in groups['k3s_server'] }}"
        k3s_server_url: "https://{{ hostvars[groups['k3s_server'][0]].ansible_default_ipv4.address }}:6443"
        k3s_node_token: "{{ hostvars[groups['k3s_server'][0]].k3s_node_token }}"
```

### Inventory Example

```ini
[k3s_server]
hl-k3s-node-0 ansible_host=10.0.1.7

[k3s_agent]
hl-k3s-node-1 ansible_host=10.0.1.40
rasp-pi-03 ansible_host=100.x.x.x
rasp-pi-04 ansible_host=100.x.x.x
```

### Advanced Configuration with Tailscale

```yaml
- name: Deploy k3s with Tailscale mesh
  hosts: all
  become: true
  vars:
    k3s_use_tailscale: true
    k3s_server_config:
      disable:
        - traefik
        - servicelb  # Use MetalLB or Tailscale Operator instead
      tls-san:
        - "{{ ansible_hostname }}.tail57bf10.ts.net"
  roles:
    - k3s
```

## Usage Workflow

### 1. Server Installation (First Run)

Execute on the designated control plane node:

```bash
ansible-playbook -i inventory.ini site.yml --limit k3s_server
```

This will:
- Install k3s in server mode
- Generate node token at `/etc/rancher/k3s/k3s-token`
- Create kubeconfig at `/etc/rancher/k3s/k3s.yaml`

### 2. Agent Installation (Subsequent Runs)

Execute on worker nodes:

```bash
ansible-playbook -i inventory.ini site.yml --limit k3s_agent
```

Agents will automatically join using the token from the server.

### 3. Verification

On the server node:

```bash
kubectl get nodes -o wide
kubectl get pods -A
```

Expected output:
```
NAME            STATUS   ROLES                  AGE   VERSION
hl-k3s-node-0   Ready    control-plane,master   5m    v1.28.5+k3s1
hl-k3s-node-1   Ready    <none>                 2m    v1.28.5+k3s1
rasp-pi-03      Ready    <none>                 1m    v1.28.5+k3s1
```

## Architecture Patterns

### Hybrid Cloud Topology

```
┌─────────────────────────────────────────────────────────┐
│ Oracle Cloud (hl-k3s-node-0)                            │
│ ┌────────────────────────────┐                          │
│ │ k3s Server (Control Plane) │                          │
│ │ - etcd embedded            │                          │
│ │ - API Server: :6443        │◄─────┐                   │
│ │ - Tailscale: 100.x.x.x     │      │                   │
│ └────────────────────────────┘      │                   │
└──────────────────────────────────────┼───────────────────┘
                                       │
                         Tailscale VPN Mesh
                                       │
┌──────────────────────────────────────┼───────────────────┐
│ On-Prem Raspberry Pi Cluster         │                   │
│                                      │                   │
│ ┌─────────────┐    ┌─────────────┐  │                   │
│ │ rasp-pi-03  │    │ rasp-pi-04  │  │                   │
│ │ k3s Agent   │    │ k3s Agent   │──┘                   │
│ │ 4GB RAM     │    │ 8GB RAM     │                      │
│ └─────────────┘    └─────────────┘                      │
└─────────────────────────────────────────────────────────┘
```

### Resource Scheduling Strategy

- **Control Plane**: Oracle Cloud (high availability, 24/7 uptime)
- **Heavy Workloads**: Oracle Cloud nodes (12GB+ RAM)
- **Edge Services**: Raspberry Pi (AdGuard DNS, monitoring agents)
- **Storage**: Mixed (OCI block storage + local NFS)

## AWS DOP-C02 Exam Parallels

> **Exam Tip**: This k3s deployment mirrors several AWS patterns tested in the DevOps Engineer - Professional exam:

### 1. Configuration Management (Domain 1: SDLC Automation)

| Homelab Pattern | AWS Equivalent |
|-----------------|----------------|
| Ansible role for k3s installation | AWS Systems Manager Run Command + Ansible playbooks |
| Dynamic inventory from Terraform | AWS Systems Manager Inventory + Parameter Store |
| Idempotent installation tasks | CloudFormation custom resources with Lambda |

**Exam Scenario**: *"Design an automated solution to configure EC2 instances for a containerized application deployment."*

- **Answer**: Use AWS Systems Manager State Manager with Ansible associations, similar to how this role ensures k3s is installed and configured idempotently.

### 2. Container Orchestration (Domain 3: Monitoring and Logging)

| Homelab Pattern | AWS Equivalent |
|-----------------|----------------|
| k3s lightweight Kubernetes | Amazon EKS (Managed Kubernetes) or ECS (simpler alternative) |
| etcd snapshots for backups | EKS control plane backups (automatic) |
| Node labels for workload placement | ECS task placement constraints or EKS node selectors |

**Exam Scenario**: *"Implement a disaster recovery strategy for a Kubernetes control plane."*

- **Answer**: Enable automated etcd snapshots (like `k3s_enable_etcd_snapshots`), store in S3 with versioning, test restore procedures quarterly.

### 3. Hybrid Networking (Domain 2: Configuration Management)

| Homelab Pattern | AWS Equivalent |
|-----------------|----------------|
| Tailscale VPN mesh | AWS Transit Gateway + VPN connections |
| Private cluster communication | VPC Peering or AWS PrivateLink |
| Dynamic server URL resolution | Route 53 private hosted zones |

**Exam Scenario**: *"Connect on-premises infrastructure to AWS workloads securely."*

- **Answer**: Use AWS Site-to-Site VPN or Direct Connect with Transit Gateway, similar to how Tailscale creates an encrypted mesh between Oracle Cloud and Raspberry Pi.

### 4. Security Best Practices (Domain 4: Incident and Event Response)

| Homelab Pattern | AWS Equivalent |
|-----------------|----------------|
| `k3s_protect_kernel_defaults` | EC2 instance hardening with CIS benchmarks |
| Token-based node authentication | IAM roles for EKS nodes (IRSA) |
| Secrets encryption at rest | KMS encryption for EKS secrets |

**Exam Scenario**: *"Implement least-privilege access for container workloads."*

- **Answer**: Use IAM Roles for Service Accounts (IRSA) in EKS, map to Kubernetes service accounts, similar to k3s node token authentication.

### 5. Resource Optimization (Domain 3: Monitoring and Logging)

| Homelab Pattern | AWS Equivalent |
|-----------------|----------------|
| Raspberry Pi max pods limit | ECS container instance limits |
| Memory-based node selection | EC2 instance type selection in Auto Scaling Groups |
| Tailscale for cost-free networking | VPC endpoints to avoid data transfer charges |

**Exam Scenario**: *"Optimize costs for a containerized application with variable traffic."*

- **Answer**: Use ECS Fargate with Spot instances + CloudWatch alarms for scaling, similar to k3s resource constraints on Pi nodes.

## Troubleshooting

### Issue: Agent fails to join cluster

**Symptom**: `k3s-agent` service fails with `Connection refused`

**Solution**:
1. Verify firewall allows port 6443: `sudo firewall-cmd --list-ports`
2. Check server URL is correct: `cat /etc/rancher/k3s/k3s-server-url`
3. Validate token: `cat /etc/rancher/k3s/k3s-token`
4. Test connectivity: `curl -k https://<server-ip>:6443`

### Issue: Pods stuck in Pending on Raspberry Pi

**Symptom**: Workloads don't schedule on Pi nodes

**Solution**:
1. Check node resources: `kubectl describe node rasp-pi-03`
2. Review resource requests: `kubectl get pod <name> -o yaml | grep -A5 resources`
3. Adjust `k3s_pi_max_pods` if needed
4. Consider taints/tolerations for workload isolation

### Issue: Tailscale connectivity issues

**Symptom**: Nodes can't communicate over Tailscale

**Solution**:
1. Verify Tailscale status: `tailscale status`
2. Check routes: `tailscale ip -4`
3. Ensure `--accept-routes` is enabled
4. Review k3s logs: `journalctl -u k3s -f`

## License

MIT

## Author

homelab project - AWS Certified DevOps Engineer - Professional study environment

## References

- [k3s Documentation](https://docs.k3s.io/)
- [Ansible Best Practices](https://docs.ansible.com/ansible/latest/user_guide/playbooks_best_practices.html)
- [AWS DOP-C02 Exam Guide](https://aws.amazon.com/certification/certified-devops-engineer-professional/)
- [Tailscale Kubernetes Operator](https://tailscale.com/kb/1236/kubernetes-operator)
