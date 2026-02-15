#!/bin/bash
# Node Labeling Script for Longhorn Storage
# This script labels nodes appropriately for Longhorn deployment
# Per conventions.md: hl- prefix for all resources

echo "========================================="
echo "Labeling Nodes for Longhorn Storage"
echo "========================================="
echo ""

# Label nodes that are capable of running Longhorn storage
# Requirements: 2GB+ RAM, open-iscsi installed
# Excluding: rasp-pi-03 (RPi 3 with only 899MB RAM)

echo "Labeling AWS nodes (k3s-server-1, k3s-agent-2)..."
kubectl label nodes k3s-server-1 hl-storage-capable=true --overwrite
kubectl label nodes k3s-agent-2 hl-storage-capable=true --overwrite

echo "Labeling RPi 4 (rasp-pi-04) - has 7.6GB RAM..."
kubectl label nodes rasp-pi-04 hl-storage-capable=true --overwrite

echo ""
echo "IMPORTANT: RPi 3 (rasp-pi-03) is intentionally NOT labeled"
echo "Reason: Only 899MB RAM - below Longhorn minimum requirement (2GB)"
echo ""

# Verify labels
echo "Current node labels:"
kubectl get nodes -L hl-storage-capable

echo ""
echo "========================================="
echo "Node labeling complete!"
echo "========================================="
