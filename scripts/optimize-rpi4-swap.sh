#!/bin/bash
# Increase RPi 4 Swap Space (IMPROVED VERSION)
# Run this on rasp-pi-04 via SSH

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "========================================="
echo "RPi 4 Swap Optimization Script"
echo "IMPROVED VERSION - With Safety Checks"
echo "========================================="
echo ""

# Check current swap
echo -e "${BLUE}Current swap status:${NC}"
free -h
echo ""
swapon -s
echo ""

# IMPROVED: Check available disk space before creating swap
echo "Checking available disk space..."
AVAILABLE_KB=$(df / | tail -1 | awk '{print $4}')
AVAILABLE_GB=$((AVAILABLE_KB / 1024 / 1024))
REQUIRED_KB=2097152  # 2GB in KB
REQUIRED_GB=2

echo "  Available: ${AVAILABLE_GB}GB"
echo "  Required:  ${REQUIRED_GB}GB"

if [ "$AVAILABLE_KB" -lt "$REQUIRED_KB" ]; then
    echo -e "${RED}ERROR: Not enough disk space!${NC}"
    echo "Need ${REQUIRED_GB}GB, have ${AVAILABLE_GB}GB"
    echo ""
    echo "Options:"
    echo "1. Free up disk space"
    echo "2. Create smaller swap (1GB instead of 2GB)"
    exit 1
fi

echo -e "${GREEN}✓ Sufficient disk space available${NC}"
echo ""

# Create 2GB swap file if it doesn't exist
if [ ! -f /swapfile ]; then
    echo -e "${BLUE}Creating 2GB swap file...${NC}"

    # IMPROVED: Try fallocate first, fall back to dd if it fails
    if sudo fallocate -l 2G /swapfile 2>/dev/null; then
        echo -e "${GREEN}✓ Created with fallocate (fast)${NC}"
    else
        echo -e "${YELLOW}⚠ fallocate failed, using dd (slower)...${NC}"
        echo "This may take 1-2 minutes..."
        sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
        echo -e "${GREEN}✓ Created with dd${NC}"
    fi

    echo "Setting permissions..."
    sudo chmod 600 /swapfile

    echo "Initializing swap..."
    sudo mkswap /swapfile
    echo -e "${GREEN}✓ Swap file created successfully${NC}"
else
    echo -e "${YELLOW}Swap file already exists at /swapfile${NC}"
fi

echo ""

# Enable swap
if ! swapon -s | grep -q /swapfile; then
    echo -e "${BLUE}Enabling swap...${NC}"
    sudo swapon /swapfile
    echo -e "${GREEN}✓ Swap enabled${NC}"
else
    echo -e "${YELLOW}Swap already enabled${NC}"
fi

echo ""

# Make permanent in fstab
if ! grep -q "/swapfile" /etc/fstab; then
    echo -e "${BLUE}Adding to /etc/fstab for persistence...${NC}"
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo -e "${GREEN}✓ Added to fstab${NC}"
else
    echo -e "${YELLOW}Already in /etc/fstab${NC}"
fi

echo ""

# Configure swappiness (lower = less aggressive swapping)
echo -e "${BLUE}Configuring swappiness...${NC}"
if ! grep -q "^vm.swappiness" /etc/sysctl.conf; then
    echo '# Reduce swappiness (less aggressive swapping)' | sudo tee -a /etc/sysctl.conf
    echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
    sudo sysctl -p
    echo -e "${GREEN}✓ Swappiness set to 10 (was default 60)${NC}"
else
    echo -e "${YELLOW}Swappiness already configured${NC}"
    CURRENT_SWAP=$(sysctl -n vm.swappiness)
    echo "  Current value: $CURRENT_SWAP"
fi

echo ""

# Configure vfs_cache_pressure
echo -e "${BLUE}Configuring VFS cache pressure...${NC}"
if ! grep -q "^vm.vfs_cache_pressure" /etc/sysctl.conf; then
    echo '# Reduce vfs_cache_pressure (keep directory/inode cache longer)' | sudo tee -a /etc/sysctl.conf
    echo 'vm.vfs_cache_pressure=50' | sudo tee -a /etc/sysctl.conf
    sudo sysctl -p
    echo -e "${GREEN}✓ VFS cache pressure set to 50 (was default 100)${NC}"
else
    echo -e "${YELLOW}VFS cache pressure already configured${NC}"
    CURRENT_CACHE=$(sysctl -n vm.vfs_cache_pressure)
    echo "  Current value: $CURRENT_CACHE"
fi

echo ""

# Verify final state
echo "========================================="
echo -e "${BLUE}Final swap status:${NC}"
free -h
echo ""
swapon -s
echo ""
echo -e "${BLUE}Memory settings:${NC}"
sysctl vm.swappiness vm.vfs_cache_pressure
echo ""

# Show improvement
echo -e "${GREEN}========================================="
echo "Swap optimization complete!"
echo "=========================================${NC}"
echo ""
echo "Summary of changes:"
echo "  • Swap size: Increased to 2GB"
echo "  • Swappiness: Reduced to 10 (less aggressive)"
echo "  • Cache pressure: Reduced to 50 (better caching)"
echo "  • All changes are persistent across reboots"
echo ""
echo -e "${YELLOW}Note:${NC} Changes take effect immediately."
echo "Your apps should now handle memory pressure better!"
echo ""
echo "To verify improvement over time:"
echo "  watch -n 5 'free -h && uptime'"
