# LLD 23: Secret Rotation Automation with Expiry Alarms

## Feature

Needed + Missed #16: Add secret rotation automation with expiry alarms.

## Scope

Add a scheduled workflow that checks a YAML policy file describing secret rotation deadlines and raises an alarm when any secret is near expiry or overdue.

- Read secret metadata from a repository YAML file.
- Compare rotation deadlines against the current date.
- Fail the scheduled job when any secret is inside the warning window.
- Keep the policy file human-editable and version-controlled.

This increment does not rotate external secrets automatically; it provides alarm automation and policy enforcement.

## Policy File

`config/secret-rotation.yml` contains a list of secrets with:

- `name`
- `owner`
- `expires_at`
- `rotation_runbook`

## Workflow Design

1. Run on a weekly schedule and on manual dispatch.
2. Load the rotation policy file.
3. Flag any secret expiring within the warning window.
4. Exit non-zero to surface the alarm in CI.

## Failure Policy

- Missing or malformed policy file fails the job.
- Expired or soon-to-expire secrets fail the job.

## Rollout

1. Add the policy file and checker.
2. Populate the first real secret list.
3. Tune the warning window based on operational lead time.
