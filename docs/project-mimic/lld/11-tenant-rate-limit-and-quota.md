# LLD 11: Tenant Rate Limit and Quota Controls

## Feature

Needed + Missed #4: Add per-tenant rate limits and request quotas.

## Scope

This increment adds in-memory tenant throttling in API middleware.

- Per-tenant requests-per-minute limit.
- Per-tenant daily request quota.
- Structured 429 errors with machine codes.

Distributed/global quota storage and billing-integrated metering are out-of-scope.

## Configuration

- `API_RATE_LIMIT_PER_MINUTE`: integer, default `0` (disabled).
- `API_DAILY_QUOTA`: integer, default `0` (disabled).

## Design

### Counters

- Minute bucket key: `(tenant_id, epoch_minute)`.
- Day bucket key: `(tenant_id, epoch_day)`.
- Buckets are pruned opportunistically during request handling.

### Enforcement Flow

1. Resolve tenant id in middleware (Feature 3).
2. Skip docs/OpenAPI routes.
3. Increment minute/day counters.
4. If minute counter exceeds limit, return 429 code `RATE_LIMITED`.
5. If day counter exceeds quota, return 429 code `QUOTA_EXCEEDED`.

## Error Behavior

- Rate limit exceeded:
  - status 429
  - code `RATE_LIMITED`
  - message `tenant rate limit exceeded`
- Quota exceeded:
  - status 429
  - code `QUOTA_EXCEEDED`
  - message `tenant daily quota exceeded`

## Test Plan

1. Rate-limit enabled: third request over limit returns 429 `RATE_LIMITED`.
2. Daily quota enabled: request over quota returns 429 `QUOTA_EXCEEDED`.
3. Existing tests continue to pass with default disabled limits.

## Rollout

1. Enable conservative limits in staging.
2. Observe rejection telemetry and tune thresholds.
3. Replace in-memory counters with durable distributed counters in follow-up feature.
