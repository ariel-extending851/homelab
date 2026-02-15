#!/bin/bash
# Emergency Recovery Script - Execute once kubectl is working
# This script will fix ***/*** access by recreating proxy StatefulSets

echo "========================================="
echo "***/*** Emergency Recovery"
echo "========================================="
echo ""

# Check if kubectl is working
echo "Checking Kubernetes API..."
if ! kubectl get nodes > /dev/null 2>&1; then
    echo "ERROR: Kubernetes API is still down. Please wait and try again."
    echo "Run this script again when 'kubectl get nodes' works."
    exit 1
fi

echo "✓ Kubernetes API is back!"
echo ""

# Show current state
echo "Current proxy status:"
kubectl get pods -n tailscale -o wide | grep -E "(***|***|***)" || echo "No proxies found"
echo ""

# Step 1: Delete failing StatefulSets
echo "Step 1: Deleting failing StatefulSets..."
echo "This breaks the 'sticky' scheduling and allows recreation on any node..."
echo ""

echo "Deleting ts-***-ingress..."
kubectl delete statefulset ts-***-ingress -n tailscale --ignore-not-found=true

echo "Deleting ts-***-ingress..."
kubectl delete statefulset ts-***-ingress -n tailscale --ignore-not-found=true

echo ""
echo "Step 2: Waiting for Tailscale operator to recreate..."
echo "This may take 30-60 seconds..."
for _ in {1..6}; do
    echo -n "."
    sleep 10

    # Check if pods are being created
    POD_COUNT=$(kubectl get pods -n tailscale -o name 2>/dev/null | grep -E "(***|***)" | wc -l)
    if [ "$POD_COUNT" -ge 2 ]; then
        echo ""
        echo "✓ Pods are being recreated!"
        break
    fi
done

echo ""
echo "Step 3: Checking new distribution..."
kubectl get pods -n tailscale -o wide | grep -E "(***|***|***)"

echo ""
echo "Step 4: Waiting for pods to be Ready..."
kubectl wait --for=condition=Ready pods -n tailscale -l tailscale.com/proxy-class=default --timeout=120s || echo "Timeout waiting for Ready status"

echo ""
echo "Step 5: Testing endpoints..."
echo "Testing ***..."
***_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://***.tail57bf10.ts.net || echo "000")
if [ "$***_STATUS" = "200" ] || [ "$***_STATUS" = "302" ]; then
    echo "✓ *** is accessible (HTTP $***_STATUS)"
else
    echo "⚠ *** returned HTTP $***_STATUS (may still be starting)"
fi

echo ""
echo "Testing ***..."
***_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://***-1.tail57bf10.ts.net || echo "000")
if [ "$***_STATUS" = "200" ] || [ "$***_STATUS" = "302" ]; then
    echo "✓ *** is accessible (HTTP $***_STATUS)"
else
    echo "⚠ *** returned HTTP $***_STATUS (may still be starting)"
fi

echo ""
echo "Testing ***..."
***_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://***.tail57bf10.ts.net || echo "000")
if [ "$***_STATUS" = "200" ] || [ "$***_STATUS" = "302" ]; then
    echo "✓ *** is accessible (HTTP $***_STATUS)"
else
    echo "⚠ *** returned HTTP $***_STATUS (may still be starting)"
fi

echo ""
echo "========================================="
echo "Recovery Complete!"
echo "========================================="
echo ""
echo "Summary:"
echo "- Deleted failing StatefulSets"
echo "- Let ArgoCD/Tailscale operator recreate them"
echo "- Pods should now be on RPi 4 (where there's 5.9GB free RAM)"
echo ""
echo "If apps are still not accessible:"
echo "1. Wait 2-3 more minutes for full startup"
echo "2. Check: kubectl get pods -n tailscale -o wide"
echo "3. If still issues, consider adding swap to RPi 3"
echo ""
