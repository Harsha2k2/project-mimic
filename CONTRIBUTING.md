# Contributing to Project Mimic

## Branch Naming Convention

Use short, structured branch names:

- `feat/<area>-<short-description>`
- `fix/<area>-<short-description>`
- `chore/<area>-<short-description>`
- `docs/<area>-<short-description>`
- `ci/<area>-<short-description>`

Examples:

- `feat/vision-entity-dedup`
- `fix/api-session-timeout`

## Commit Message Convention

Use Conventional Commit style:

- `feat(scope): ...`
- `fix(scope): ...`
- `chore(scope): ...`
- `docs(scope): ...`
- `ci(scope): ...`
- `test(scope): ...`

Each commit must include:

1. One focused feature or fix.
2. Updated tests for behavioral change.
3. Passing test evidence locally (`make test`).

## Pull Request Rules

1. Keep pull requests scoped and reviewable.
2. Include test plan and risk notes.
3. Link related issue IDs.
4. Ensure CI is fully green.

## Triage and Labels

Issue and PR triage is defined in [Triage Policy](.github/TRIAGE_POLICY.md).
Release note labels are defined in [.github/labels.yml](.github/labels.yml).
