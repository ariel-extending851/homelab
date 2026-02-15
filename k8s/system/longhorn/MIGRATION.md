# Storage Migration Plan: Local-Path → Longhorn

## Executive Summary

**Objective:** Migrate ***, ***, and *** from `rasp-pi-04` local storage to Longhorn distributed storage on AWS nodes.

**Expected Outcome:**
- Reduced load on RPi 4 (currently overloaded)
- Better performance on x86_64 AWS nodes
- Data redundancy with 2 replicas
- Ability to migrate workloads dynamically

**Risk Level:** Medium (configuration data migration)

---

## Pre-Migration Checklist

- [ ] Longhorn fully deployed and verified
- [ ] All PVC backups completed
- [ ] ArgoCD sync disabled for target apps
- [ ] Maintenance window communicated
- [ ] Rollback plan tested

---

## Application Analysis

### ***

**Current State:**
- Node: `rasp-pi-04`
- PVC: `***-config` (local-path)
- CPU: 2000m limit
- Status: Slow/CPU-throttled

**Migration Complexity:** Medium
- Configuration: TV show database (~100MB typical)
- Data Volume: Low
- Downtime: ~5 minutes

**Migration Steps:**
1. Stop *** deployment
2. Backup existing PVC to S3/temp location
3. Create new Longhorn PVC
4. Restore data to new PVC
5. Update deployment:
   - Change `nodeSelector` to AWS node
   - Change `storageClassName` to `hl-longhorn`
6. Verify functionality

### ***

**Current State:**
- Node: `rasp-pi-04`
- PVC: `***-config` (local-path)
- CPU: 2000m limit
- Status: Slow/CPU-throttled

**Migration Complexity:** Medium
- Configuration: Movie database (~100MB typical)
- Data Volume: Low
- Downtime: ~5 minutes

**Migration Steps:**
1. Stop *** deployment
2. Backup existing PVC
3. Create new Longhorn PVC
4. Restore data to new PVC
5. Update deployment to AWS node + Longhorn
6. Verify functionality

### ***

**Current State:**
- Node: `rasp-pi-04`
- PVC: `***-config` (local-path)
- CPU: 500m limit
- Status: Slow

**Migration Complexity:** Low
- Configuration: Indexer definitions (~50MB typical)
- Data Volume: Very Low
- Downtime: ~2 minutes

**Migration Steps:**
1. Stop *** deployment
2. Backup existing PVC
3. Create new Longhorn PVC
4. Restore data
5. Update deployment
6. Verify functionality

---

## Detailed Migration Procedure

### Phase 1: Pre-Migration (Do Once)

```bash
# 1. Create backup directory
mkdir -p /tmp/longhorn-migration-$(date +%Y%m%d)
BACKUP_DIR=/tmp/longhorn-migration-$(date +%Y%m%d)

# 2. Document current PVCs
echo "Current PVCs on rasp-pi-04:"
kubectl get pvc -A -o json | jq -r '.items[] | select(.spec.nodeSelector? != null) | "\(.metadata.namespace)/\(.metadata.name) -> \(.spec.nodeSelector)"'

# 3. Verify Longhorn is healthy
kubectl get pods -n hl-longhorn
echo "Longhorn nodes:"
kubectl get nodes -L hl-storage-capable
```

### Phase 2: *** Migration (Pilot - Lowest Risk)

```bash
#!/bin/bash
# migrate-***.sh

APP_NAME=***
NAMESPACE=default
OLD_PVC=***-config
NEW_PVC=***-config-longhorn

# Step 1: Scale down
echo "Scaling down ***..."
kubectl scale deployment $APP_NAME --replicas=0

# Step 2: Create backup
echo "Creating backup..."
kubectl cp $NAMESPACE/$APP_NAME-xxx:/config $BACKUP_DIR/$APP_NAME-backup

# Step 3: Create new PVC with Longhorn
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $NEW_PVC
  namespace: $NAMESPACE
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: hl-longhorn
  resources:
    requests:
      storage: 1Gi
EOF

# Step 4: Wait for PVC to be bound
echo "Waiting for PVC to bind..."
kubectl wait --for=jsonpath='{.status.phase}'=Bound pvc/$NEW_PVC --timeout=60s

# Step 5: Restore data
echo "Restoring data..."
# Create temporary pod to copy data
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: $APP_NAME-restore
  namespace: $NAMESPACE
spec:
  containers:
  - name: restore
    image: busybox
    command: ["sleep", "3600"]
    volumeMounts:
    - name: new-config
      mountPath: /new-config
  volumes:
  - name: new-config
    persistentVolumeClaim:
      claimName: $NEW_PVC
  restartPolicy: Never
EOF

kubectl wait --for=condition=Ready pod/$APP_NAME-restore --timeout=60s
kubectl cp $BACKUP_DIR/$APP_NAME-backup $NAMESPACE/$APP_NAME-restore:/new-config
kubectl delete pod $APP_NAME-restore

# Step 6: Update deployment
echo "Updating deployment..."
kubectl patch deployment $APP_NAME --type=json -p='[
  {"op": "replace", "path": "/spec/template/spec/nodeSelector", "value": {"kubernetes.io/os": "linux", "kubernetes.io/arch": "amd64"}},
  {"op": "replace", "path": "/spec/template/spec/volumes/0/persistentVolumeClaim/claimName", "value": "$NEW_PVC"}
]'

# Step 7: Scale up
echo "Scaling up..."
kubectl scale deployment $APP_NAME --replicas=1

# Step 8: Verify
echo "Verifying..."
kubectl rollout status deployment/$APP_NAME
kubectl get pods -l app=$APP_NAME -o wide

echo "*** migration complete!"
```

### Phase 3: *** Migration

Follow same procedure as *** with these changes:

```bash
APP_NAME=***
NAMESPACE=default
OLD_PVC=***-config
NEW_PVC=***-config-longhorn
PVC_SIZE=5Gi  # Larger for ***
```

### Phase 4: *** Migration

Follow same procedure as *** with these changes:

```bash
APP_NAME=***
NAMESPACE=default
OLD_PVC=***-config
NEW_PVC=***-config-longhorn
PVC_SIZE=5Gi
```

---

## Deployment Changes Required

### *** Deployment Changes

```yaml
# Add nodeSelector to target AWS nodes
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.io/os: linux
        kubernetes.io/arch: amd64
      containers:
        - name: ***
          # Existing config...
      volumes:
        - name: config
          persistentVolumeClaim:
            claimName: ***-config-longhorn  # New PVC name
```

### *** Deployment Changes

```yaml
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.io/os: linux
        kubernetes.io/arch: amd64
      volumes:
        - name: config
          persistentVolumeClaim:
            claimName: ***-config-longhorn
```

### *** Deployment Changes

```yaml
spec:
  template:
    spec:
      nodeSelector:
        kubernetes.io/os: linux
        kubernetes.io/arch: amd64
      volumes:
        - name: config
          persistentVolumeClaim:
            claimName: ***-config-longhorn
```

---

## Post-Migration Verification

### Performance Checks

```bash
# Check pod scheduling
echo "Pod distribution after migration:"
kubectl get pods -l "app in (***, ***, ***)" -o wide

# Check resource usage
echo "Resource usage:"
kubectl top pods -l "app in (***, ***, ***)"

# Check Longhorn volumes
echo "Longhorn volumes:"
kubectl get pvc -l "app in (***, ***, ***)"

# Access UI and verify functionality
echo "Testing endpoints..."
curl -s https://***.tail57bf10.ts.net/api/v1/health
curl -s https://***.tail57bf10.ts.net/api/v3/health
curl -s https://***-1.tail57bf10.ts.net/api/v3/health
```

### Data Integrity Checks

```bash
# Verify configurations preserved
kubectl exec -it deploy/*** -- ls -la /config/
kubectl exec -it deploy/*** -- ls -la /config/
kubectl exec -it deploy/*** -- ls -la /config/

# Check database files
kubectl exec -it deploy/*** -- find /config -name "*.db" -type f
kubectl exec -it deploy/*** -- find /config -name "*.db" -type f
```

---

## Rollback Procedure

If migration fails:

```bash
#!/bin/bash
# rollback.sh

APP_NAME=$1  # ***, ***, or ***

echo "Rolling back $APP_NAME..."

# 1. Scale down
kubectl scale deployment $APP_NAME --replicas=0

# 2. Restore old PVC reference
kubectl patch deployment $APP_NAME --type=json -p='[
  {"op": "replace", "path": "/spec/template/spec/nodeSelector", "value": {"kubernetes.io/hostname": "rasp-pi-04"}},
  {"op": "replace", "path": "/spec/template/spec/volumes/0/persistentVolumeClaim/claimName", "value": "$APP_NAME-config"}
]'

# 3. Scale up
kubectl scale deployment $APP_NAME --replicas=1

# 4. Verify
kubectl rollout status deployment/$APP_NAME

echo "Rollback complete!"
```

---

## Cleanup (After 1 Week Stable)

Once migration is verified stable:

```bash
# Delete old local-path PVCs
kubectl delete pvc ***-config
kubectl delete pvc ***-config
kubectl delete pvc ***-config

# Clean up backups
rm -rf $BACKUP_DIR

# Update ArgoCD Application to point to new PVCs
# Commit changes to Git
```

---

## Timeline

| Phase | Duration | Downtime |
|-------|----------|----------|
| Longhorn Deployment | 15 min | None |
| *** Migration | 10 min | 2 min |
| *** Migration | 15 min | 5 min |
| *** Migration | 15 min | 5 min |
| Verification | 10 min | None |
| **Total** | **65 min** | **12 min** |

---

## Success Criteria

✅ All apps accessible via Tailscale URLs
✅ Response times under 2 seconds (vs current 10+ seconds)
✅ CPU usage under 50% on AWS nodes
✅ RPi 4 load average below 2.0
✅ All configurations preserved
✅ No data loss

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Data loss during migration | High | Full backups before migration |
| Longhorn instability | Medium | Conservative resource limits, rollback plan |
| Extended downtime | Medium | Pilot migration with *** first |
| AWS node resource exhaustion | Medium | Monitor during migration, scale back if needed |
| Network storage performance | Low | Test with small workload first |

---

## Appendix: ArgoCD Application Updates

After successful migration, update these files:

- `k8s/apps/***/deployment.yaml` - Update PVC reference
- `k8s/apps/***/deployment.yaml` - Update PVC reference
- `k8s/apps/***/deployment.yaml` - Update PVC reference
- Remove `nodeSelector: kubernetes.io/hostname: rasp-pi-04`

Commit these changes to `develop` branch.
