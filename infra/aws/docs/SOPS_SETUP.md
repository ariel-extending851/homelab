# SOPS Setup Guide for AWS Homelab

This guide explains how to set up SOPS (Secrets OPerationS) to securely manage sensitive Terraform variables.

## 🔐 Why SOPS?

SOPS allows you to:
- ✅ **Encrypt secrets** at rest in version control
- ✅ **Track encrypted files** in Git safely
- ✅ **Decrypt automatically** during Terraform operations
- ✅ **Use AGE encryption** (modern, simple, secure)

## 📋 Prerequisites

Install required tools:

```bash
# Install SOPS
# macOS
brew install sops

# Linux
wget https://github.com/mozilla/sops/releases/download/v3.8.1/sops-v3.8.1.linux.amd64
sudo mv sops-v3.8.1.linux.amd64 /usr/local/bin/sops
sudo chmod +x /usr/local/bin/sops

# Install AGE (encryption tool)
# macOS
brew install age

# Linux
wget https://github.com/FiloSottile/age/releases/download/v1.1.1/age-v1.1.1-linux-amd64.tar.gz
tar xzf age-v1.1.1-linux-amd64.tar.gz
sudo mv age/age age/age-keygen /usr/local/bin/
```

## 🔑 Step 1: Generate AGE Key

Create a new AGE key pair (only once):

```bash
# Create SOPS config directory
mkdir -p ~/.config/sops/age

# Generate AGE key
age-keygen -o ~/.config/sops/age/keys.txt

# IMPORTANT: Backup this file securely!
# Without it, you CANNOT decrypt your secrets!
```

## 📝 Step 2: Get Your Public Key

```bash
# Display your public key
grep "# public key:" ~/.config/sops/age/keys.txt

# Example output:
# public key: age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja
```

**⚠️ CRITICAL:** Save your AGE public key - you'll need it for encryption!

## 🔧 Step 3: Configure Environment

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
# SOPS Configuration
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
```

Reload your shell:
```bash
source ~/.bashrc  # or ~/.zshrc
```

## ✏️ Step 4: Edit Secrets File

The `terraform.tfvars.sops.yaml` file is a template. Edit it with your actual values:

```bash
cd /var/mnt/nvme/repos/repos/homelab/infra/aws

# Generate SSH key (if needed)
ssh-keygen -t ed25519 -C "homelab-aws" -f ~/.ssh/homelab-aws

# Generate k3s token
openssl rand -base64 32

# Edit the SOPS file with your values
nano terraform.tfvars.sops.yaml
```

Update these values:
```yaml
ssh_public_key: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... homelab-aws"
k3s_token: "your-actual-token-from-openssl-command"
```

## 🔒 Step 5: Encrypt the File

Now encrypt your secrets with SOPS:

```bash
# Replace YOUR_AGE_PUBLIC_KEY with your actual public key
sops --encrypt \
  --age YOUR_AGE_PUBLIC_KEY \
  --encrypted-regex '^(ssh_public_key|k3s_token)$' \
  terraform.tfvars.sops.yaml > terraform.tfvars.sops.yaml.enc

# Replace original with encrypted version
mv terraform.tfvars.sops.yaml.enc terraform.tfvars.sops.yaml
```

**Example:**
```bash
sops --encrypt \
  --age age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja \
  --encrypted-regex '^(ssh_public_key|k3s_token)$' \
  terraform.tfvars.sops.yaml > terraform.tfvars.sops.yaml.enc

mv terraform.tfvars.sops.yaml.enc terraform.tfvars.sops.yaml
```

## ✅ Step 6: Verify Encryption

Check that your file is encrypted:

```bash
cat terraform.tfvars.sops.yaml
```

You should see something like:
```yaml
ssh_public_key: ENC[AES256_GCM,data:TqBfkzXfOBrsLx4cY...==,type:str]
k3s_token: ENC[AES256_GCM,data:4IWHpYq44di5UHxVF...==,type:str]
sops:
    age:
        - recipient: age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja
          enc: |
            -----BEGIN AGE ENCRYPTED FILE-----
            ...
            -----END AGE ENCRYPTED FILE-----
```

## 🛠️ Common Operations

### View Encrypted File
```bash
sops --decrypt terraform.tfvars.sops.yaml
```

### Edit Encrypted File
SOPS will decrypt, open your editor, then re-encrypt on save:
```bash
sops terraform.tfvars.sops.yaml
```

### Add New Secrets
1. Edit with SOPS: `sops terraform.tfvars.sops.yaml`
2. Add your new key-value pair
3. Save and exit (SOPS auto-encrypts)
4. Update `.sops.yaml` encrypted-regex if needed

### Rotate AGE Key
```bash
# Generate new key
age-keygen -o ~/.config/sops/age/keys-new.txt

# Re-encrypt all files with new key
sops --rotate --age NEW_PUBLIC_KEY terraform.tfvars.sops.yaml

# Update SOPS_AGE_KEY_FILE environment variable
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys-new.txt"
```

## 🚀 Using with Terraform

Terraform will automatically decrypt via the SOPS provider:

```bash
# Initialize (downloads SOPS provider)
terraform init

# Plan (SOPS decrypts automatically)
terraform plan

# Apply
terraform apply
```

## 🔐 Security Best Practices

1. **Backup Your AGE Key**
   ```bash
   # Encrypted backup to external drive
   cp ~/.config/sops/age/keys.txt /path/to/secure/backup/
   ```

2. **Never Commit Unencrypted Secrets**
   - Always verify file is encrypted before `git add`
   - Check with: `cat terraform.tfvars.sops.yaml | grep ENC`

3. **Use `.sops.yaml` Configuration**
   Create `.sops.yaml` in project root for automatic encryption:
   ```yaml
   creation_rules:
     - path_regex: terraform\.tfvars\.sops\.yaml$
       age: age18mumpukzfug863dw7j3w2tntfd6y8nf34hzx07u2fep633mprqmqc3myja
       encrypted_regex: '^(ssh_public_key|k3s_token)$'
   ```

4. **Restrict File Permissions**
   ```bash
   chmod 600 ~/.config/sops/age/keys.txt
   chmod 600 terraform.tfvars.sops.yaml
   ```

## 🆘 Troubleshooting

### Error: "no SOPS data found in file"
**Cause:** File is not encrypted yet.
**Solution:** Follow Step 5 to encrypt the file.

### Error: "could not decrypt data key with any master key"
**Cause:** Wrong AGE key or SOPS_AGE_KEY_FILE not set.
**Solution:**
```bash
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
```

### Error: "age: no identity matched any recipient"
**Cause:** The file was encrypted with a different AGE key.
**Solution:** Use the correct AGE key file or re-encrypt with your current key.

### Terraform can't decrypt SOPS file
**Cause:** SOPS provider not initialized or AGE key not found.
**Solution:**
```bash
# Verify environment variable
echo $SOPS_AGE_KEY_FILE

# Re-initialize Terraform
terraform init

# Verify SOPS file is readable
sops --decrypt terraform.tfvars.sops.yaml
```

## 📚 Resources

- [SOPS Documentation](https://github.com/mozilla/sops)
- [AGE Encryption](https://github.com/FiloSottile/age)
- [Terraform SOPS Provider](https://registry.terraform.io/providers/carlpett/sops/latest/docs)

## 🎓 Tech Lead Reminder

**❌ NEVER commit unencrypted secrets to Git!**

Before committing:
```bash
# Verify encryption
cat terraform.tfvars.sops.yaml | head -5

# Should see: ENC[AES256_GCM,data:...
# NOT: ssh_public_key: "ssh-ed25519 AAAA..."
```

---

**Next Steps:** Once SOPS is configured, proceed to [README.md](./README.md) for Terraform deployment.
