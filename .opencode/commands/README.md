# OpenCode Custom Commands

This directory contains custom commands for OpenCode to streamline development workflows in the homelab project.

## Available Commands

### `/review` - Pre-Commit Code Review
Automatically reviews staged changes before committing using the Tech Lead agent.

**What it checks:** Security issues, Pi memory limits, naming conventions, ARM64 compatibility
**Blocks on:** Secrets, missing resource limits, :latest tags in production

```bash
/commit  # Runs /review automatically
```

---

### `/commit` - Conventional Commit Generator
Generate GPG-signed Conventional Commits with detailed body.

```bash
/commit
```

---

### `/test` - Context-Aware Testing
Run appropriate tests and linters based on file types.

```bash
/test
```

---

### `/plan` - Progress Tracking
Review progress and update `.opencode/plan.md` automatically.

```bash
/plan
```

---

### `/learn` - Knowledge Acquisition
Learn about a specific topic or codebase pattern.

```bash
/learn <topic>
```

---

### `/bug` - Bug Investigation
Investigate bugs using strict TDD (Reproduction First).

```bash
/bug <issue_description>
```

---

### `/rollback` - ArgoCD Application Rollback
Rollback an ArgoCD application to a previous healthy revision.

**Features:** Manual rollback with confirmation, revision history, incident documentation
**Requirements:** ArgoCD CLI, kubectl access to argocd namespace

```bash
/rollback                      # List applications
/rollback ***             # Rollback specific app
```

---

### `/deploy-verify` - Deployment Verification
Verify deployment health after ArgoCD sync completes.

**Features:** ArgoCD sync/health status, pod status checks, formatted reports
**Requirements:** kubectl, jq for JSON parsing

```bash
/deploy-verify                 # Check all apps
/deploy-verify ***        # Check specific app
```

---

### `/pr-resolve` - PR Conversation Resolution
Automatically resolve all review threads on a PR with replies.

**Features:** Auto-detects PR, replies to threads, resolves via GraphQL
**Requirements:** GitHub CLI with write access

```bash
/pr-resolve       # Auto-detect from branch
/pr-resolve 59    # Specific PR
```

---

### `/pr-review` - PR Status Viewer
View comprehensive PR status with CI checks and review conversations.

**Features:** Shows CI status, highlights Gemini comments, parses priority badges
**Verbose mode:** Add `-v` or `--verbose` for full details

```bash
/pr-review        # Auto-detect from branch
/pr-review 59     # Specific PR
/pr-review -v     # Verbose mode
```

---

## Quick Reference

| Command | Purpose | Auto-Run |
|---------|---------|----------|
| `/review` | Pre-commit security & quality checks | Via `/commit` |
| `/commit` | Generate conventional commit | Manual |
| `/test` | Run linters and validators | Manual |
| `/plan` | Update progress tracking | Manual |
| `/learn` | Research topics | Manual |
| `/bug` | TDD bug investigation | Manual |
| `/rollback` | ArgoCD application rollback | Manual |
| `/deploy-verify` | Post-deployment health verification | Manual |
| `/pr-resolve` | Resolve PR conversations | Manual |
| `/pr-review` | View PR status | Manual |

---

## Command Development Guidelines

When creating new commands:

1. Use YAML frontmatter with `description` field
2. Structure with numbered sections (3-5 max)
3. Keep under 100 lines (aim for 20-50)
4. Provide one concise usage example
5. Document requirements if external tools needed

## Technical Architecture

### PR Commands
- **API:** GitHub CLI + GraphQL API
- **Auto-detection:** `gh pr list --head $(git branch --show-current)`
- **Authentication:** Uses `gh auth` credentials

### Review Integration
- `/commit` automatically invokes `/review` before generating commit message
- Review results saved to `.opencode/last-review.md`
- Tech Lead agent evaluates against project conventions

---

**Total Commands:** 10
**Last Updated:** 2026-01-25
