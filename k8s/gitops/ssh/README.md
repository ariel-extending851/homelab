# ArgoCD SSH Keys

ED25519 keypair for ArgoCD → GitHub authentication. Private key gitignored; public key paired with a read-only GitHub Deploy Key.

For setup and rotation procedures see **[docs/architecture/gitops.md#repository-configuration](../../../docs/architecture/gitops.md#repository-configuration)**.

## Files

| File | Purpose |
|---|---|
| `argocd`     | ED25519 private key (gitignored) |
| `argocd.pub` | ED25519 public key (gitignored, safe to share) |
| `.gitignore` | Excludes the above from VCS |
