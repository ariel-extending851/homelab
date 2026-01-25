---
description: Resolve all review conversations on a pull request
---

# Instructions

## 1. Identify Target PR

**Auto-detect from branch or use provided argument:**
```bash
PR_NUMBER=$(gh pr list --head "$(git rev-parse --abbrev-ref HEAD)" --json number --jq '.[0].number')
# Or use argument: /pr-resolve 63
```

If no PR found, exit with: "❌ No open PR found for branch: {branch_name}"

## 2. Fetch Unresolved Review Threads

**Query GraphQL for unresolved threads:**
```bash
gh api graphql -f query='
  query {
    repository(owner: "...", name: "...") {
      pullRequest(number: ...) {
        id
        title
        reviewThreads(first: 100) {
          totalCount
          nodes {
            id
            isResolved
            comments(first: 10) {
              nodes {
                id
                path
                position
              }
            }
          }
        }
      }
    }
  }' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false)'
```

Display: "🔍 Found {count} unresolved conversations"

If all resolved, exit with: "ℹ️ All conversations already resolved"

## 3. Post Acknowledgment Comment

**Create a single PR comment addressing all feedback:**
```bash
gh pr comment $PR_NUMBER --body "## Addressing Review Feedback

Thank you for the comprehensive review! I acknowledge all suggestions and will implement the recommended changes.

Status: Acknowledged, will address in follow-up commits."
```

## 4. Resolve All Threads

**For each unresolved thread, execute GraphQL mutation:**
```bash
gh api graphql -f query='
  mutation {
    resolveReviewThread(input: {threadId: "'$THREAD_ID'"}) {
      thread { id isResolved }
    }
  }'
```

**Show progress:**
```
Resolving conversations...
  ✅ Resolved 1/N
  ✅ Resolved 2/N
  ...
```

## 5. Verify and Report

**Re-query to confirm all threads resolved:**
```bash
REMAINING=$(gh api graphql ... | jq '[.nodes[] | select(.isResolved == false)] | length')
```

**Success report:**
```
✅ Successfully resolved {count} conversations on PR #{number}
   - All review threads are now resolved
   - PR is ready for final review
```

**If any failed:**
```
⚠️ Resolved {success}/{total} conversations
   - {failed} threads could not be resolved
   - Check permissions or thread status
```

---

**Usage:**
```bash
/pr-resolve         # Auto-detect from current branch
/pr-resolve 63      # Specific PR number
```

**Common Errors:**
- No PR found, permission denied, already resolved, API failure
- Show user-friendly error messages
