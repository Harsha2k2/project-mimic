# Triage Policy

## Priority Levels

- `priority:p0`: Production outage or severe data loss risk.
- `priority:p1`: Critical user path degraded without workaround.
- `priority:p2`: Important issue with workaround available.
- `priority:p3`: Low urgency backlog item.

## Type Labels

- `type:bug`
- `type:feature`
- `type:incident`
- `type:chore`

## Triage Flow

1. Assign `triage:needs-review` on creation.
2. Validate reproduction and impact.
3. Add type and priority labels.
4. Add release-note label when merged.
5. Transition to `triage:ready` when acceptance criteria are clear.

## Release Note Labels

- `release-note:major`
- `release-note:minor`
- `release-note:patch`
- `release-note:none`
