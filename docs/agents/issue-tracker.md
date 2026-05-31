# Issue Tracker: GitHub

Issues for this repository are tracked in **GitHub Issues**.

**Repository**: `pbkansara_tkinc/AISystemDesignCopilot`

## Workflow

Skills that create or update issues (`/to-issues`, `/to-prd`, `/triage`) use the **`gh` CLI** to interact with GitHub.

### Prerequisites

Ensure the `gh` CLI is installed and authenticated:

```bash
gh auth status
```

If not authenticated, run:

```bash
gh auth login
```

### Creating Issues

```bash
gh issue create --title "Title" --body "Description" --label "needs-triage"
```

### Updating Issues

```bash
gh issue edit <issue-number> --add-label "ready-for-agent"
```

### Listing Issues

```bash
gh issue list --label "needs-triage"
```

## Issue Lifecycle

1. **Created** → labeled `needs-triage`
2. **Triaged** → moved to `needs-info`, `ready-for-agent`, `ready-for-human`, or `wontfix`
3. **In Progress** → assigned to developer/agent
4. **Completed** → closed

## References

- [GitHub CLI documentation](https://cli.github.com/manual/)
- [GitHub Issues documentation](https://docs.github.com/en/issues)
