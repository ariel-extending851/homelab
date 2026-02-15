#!/bin/bash
# Install open-iscsi prerequisite on all nodes for Longhorn
# This must be run on EACH node before installing Longhorn

echo "========================================="
echo "Installing open-iscsi Prerequisites"
echo "========================================="
echo ""

# Function to install on Ubuntu/Debian
install_ubuntu() {
    echo "Detected Ubuntu/Debian system"
    sudo apt-get update
    sudo apt-get install -y open-iscsi
    sudo systemctl enable --now iscsid
    echo "open-iscsi installed and started"
}

# Function to install on RHEL/CentOS/Fedora/Rocky
install_rhel() {
    echo "Detected RHEL/CentOS/Fedora system"
    sudo dnf install -y iscsi-initiator-utils
    sudo systemctl enable --now iscsid
    echo "iscsi-initiator-utils installed and started"
}

# Detect OS and install accordingly
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case $ID in
        ubuntu|debian)
            install_ubuntu
            ;;
        rhel|centos|fedora|rocky|almalinux)
            install_rhel
            ;;
        *)
            echo "Unknown distribution: $ID"
            echo "Please install open-iscsi manually"
            exit 1
            ;;
    esac
else
    echo "Cannot detect OS"
    exit 1
fi

# Verify installation
echo ""
echo "Verifying iscsid service..."
sudo systemctl status iscsid --no-pager

echo ""
echo "Checking iscsiadm..."
sudo iscsiadm --version

echo ""
echo "========================================="
echo "Prerequisites installed successfully!"
echo "========================================="
echo ""
echo "This node is now ready for Longhorn storage."
echo ""
echo "NOTE: If this is rasp-pi-03 (RPi 3), Longhorn will NOT use this node"
echo "due to insufficient RAM (899MB < 2GB minimum requirement)"
