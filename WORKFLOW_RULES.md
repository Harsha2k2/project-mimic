# Development Workflow Rules

This file captures the mandatory engineering workflow for this repository.

## Commit and Delivery Discipline

1. Implement one feature at a time.
2. Add or update tests for every feature change.
3. Run tests before every commit.
4. Commit only when tests pass.
5. Push each feature commit to remote.
6. Avoid bulk commits that bundle unrelated features.

## Quality Bar

1. Keep code clean, modular, and readable.
2. Avoid temporary fixes that leave behind sloppy code.
3. If a bug fix introduces temporary workarounds, remove cleanup debt in the same feature cycle.
4. Re-run tests after cleanup to confirm no regression.

## Regression Policy

1. Test failures block commits.
2. Do not merge or push known failing states.
3. Maintain a dedicated test folder and expand coverage with each feature.

## Tooling Policy

1. Prefer proven open-source tools and frameworks.
2. Keep architecture and folder structure explicit and maintainable.
3. Keep CI green on push.

## Credential Handling

Use credentials provided by the repository owner through secure channels when an authenticated git prompt appears.
