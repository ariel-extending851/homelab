---
description: View PR status including reviews, CI checks, and Gemini feedback
---

# Instructions

## 1. Identify Target PR

**Auto-detect from branch or use provided argument:**
```bash
PR_NUMBER=$(gh pr list --head "$(git rev-parse --abbrev-ref HEAD)" --json number --jq '.[0].number')
# Or use argument: /pr-review 63
```

If no PR found, exit with: "❌ No open PR found for branch: {branch_name}"

## 2. Fetch PR Data

**Use GitHub CLI to gather all data:**
```bash
# Basic PR info
gh pr view $PR_NUMBER --json number,title,state,author,baseRefName,headRefName,commits,changedFiles,additions,deletions

# CI checks
gh pr checks $PR_NUMBER --json name,state,conclusion,startedAt,completedAt

# Review threads via GraphQL
gh api graphql -f query='
  query {
    repository(owner: "...", name: "...") {
      pullRequest(number: ...) {
        reviewThreads(first: 100) {
          totalCount
          nodes {
            id
            isResolved
            comments(first: 10) {
              nodes {
                author { login }
                body
                path
                position
              }
            }
          }
        }
      }
    }
  }'
```

## 3. Generate Markdown Report

**Output format:**
```markdown
# Pull Request #{number}: {title}

**Status:** {🟢 OPEN | 🔴 CLOSED | 🟣 MERGED}
**Author:** @{author} | **Base:** `{base}` ← **Head:** `{head}`
**Changes:** {commits} commits • {files} files • +{add} -{del}

## CI Status: {✅ All Passing | ❌ Failing | ⏳ Pending} ({passing}/{total})
| Check | Status | Duration |
|-------|--------|----------|
| ... | ✅/❌ | Xs |

## Review Conversations: {✅ All Resolved | ⚠️ Pending} ({resolved}/{total})
### {priority} Thread {n}: {title} - {RESOLVED/UNRESOLVED}
**File:** `{path}:{line}` | **Reviewer:** {🤖 if bot}{author}
> {comment_preview}...

## Summary
🎯 **PR Health:** {✅ Ready to Merge | ⚠️ Needs Attention | ❌ Blocked}

**Suggested Action:**
{gh pr merge command OR fix instructions}
```

**Formatting rules:**
- Use emojis for visual status (🟢🔴🟡✅❌⚠️)
- Highlight Gemini Code Assist with 🤖 emoji
- Parse priority badges: `![high]` → 🔴, `![medium]` → 🟡, `![low]` → 🟢
- Show unresolved threads first
- Truncate comment bodies to ~150 chars (use `--verbose` for full text)

## 4. Determine PR Health

**Logic:**
- ✅ **Ready:** All CI passing + all conversations resolved
- ❌ **Blocked:** CI failures or >2 unresolved conversations
- ⚠️ **Needs Attention:** Otherwise

---

**Usage:**
```bash
/pr-review          # Auto-detect from current branch
/pr-review 63       # Specific PR number
/pr-review -v       # Verbose mode (full comment bodies)
```

**Common Errors:**
- No PR found, API rate limit, network failure, invalid PR number
- Show user-friendly error messages with suggested fixes
