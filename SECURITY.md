# Security Policy

## Reporting a Vulnerability

We take the security of this homelab infrastructure and repository seriously. If you discover a security vulnerability, we appreciate your help in disclosing it to us responsibly.

> [!WARNING]
> **Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**
> Public disclosure exposes infrastructure before a fix can be prepared and deployed.

### Official Reporting Channels

1. **GitHub Private Vulnerability Reporting (Preferred)**:
   Please submit a confidential advisory directly through GitHub:
   👉 [Submit a Security Advisory](https://github.com/ariel-extending851/homelab/security/advisories/new)

   This allows encrypted, private discussion and collaborative remediation directly within GitHub's security tools.

2. **Email Disclosure (Alternative)**:
   If you cannot use GitHub Security Advisories, send an email to:
   📧 `50802265+ariel99gf@users.noreply.github.com`

   Include `[SECURITY] Vulnerability Report: <Title>` in the subject line.

---

## Supported Versions

Security updates are applied to the active development and release branches:

| Branch / Version | Supported          | Status |
| ---------------- | ------------------ | ------ |
| `develop`        | :white_check_mark: | Active development & primary integration |
| `main`           | :white_check_mark: | Production releases |
| `< v1.0 / tags`  | :x:                | Historical tags (not maintained) |

---

## Scope of Vulnerability Research

### In-Scope

- **Secrets & Credentials Leakage**: Exposure of unencrypted private keys (SSH, age, PGP), tokens, or plaintext passwords in code, history, or documentation.
- **Network Isolation & Zero Trust Escapes**:
  - Bypassing VLAN 9 (Guest / Work) isolation to reach Admin LAN (`192.168.8.0/24`) or the upstream modem subnet (`192.168.0.0/24`).
  - Bypassing IoT network isolation.
  - Bypassing DNS interception / hijacking (UDP/TCP port 53) or DNS-over-TLS (port 853) enforcement.
- **Kubernetes Security**:
  - Privilege escalation, container breakouts, or NetworkPolicy bypasses in `k8s/apps/` and `k8s/system/`.
- **Infrastructure & Cloud (AWS)**:
  - IAM least-privilege bypasses, unauthorized ingress via Security Groups, or metadata service (IMDSv2) circumvention.
- **CI/CD & Supply Chain**:
  - Compromises in GitHub Actions workflows, unauthorized workflow execution, or secret extraction via runner misconfiguration.

### Out-of-Scope

- Volumetric Denial of Service (DoS/DDoS) attacks against physical home hardware (e.g. crashing Raspberry Pi boards via flood).
- Physical access attacks against physical devices in the home.
- Social engineering (phishing, vishing) targeting maintainers or contributors.
- Reports from automated vulnerability scanners without a working proof-of-concept demonstrating actionable impact.

---

## Response Timeline & SLA

We are committed to responding promptly to legitimate security reports:

- **Initial Acknowledgment**: Within 48 hours of receipt.
- **Triage & Severity Assessment**: Within 5 business days.
- **Fix Development & Testing**: Prioritized based on severity (P0 critical issues targeted within 7 days).
- **Coordinated Disclosure**: Fixes will be merged and released, followed by public acknowledgment (if desired by the researcher).

---

## Safe Harbor

We consider security research conducted under this policy to be:
- **Authorized** under applicable anti-hacking laws.
- **Protected** from legal action by us, provided you:
  - Make a good-faith effort to avoid privacy violations, destruction of data, and service disruption.
  - Give us reasonable time to remediate the vulnerability before public disclosure.
  - Do not exploit a security issue beyond the minimum necessary to demonstrate its presence.

Thank you for helping keep this homelab and its community secure!
