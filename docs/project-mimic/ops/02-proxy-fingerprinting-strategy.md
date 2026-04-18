# Ops: Proxy Rotation and Session Fingerprinting Strategy

## 1) Objective

Provide stable and realistic session identity across distributed execution while preserving reliability and compliance.

## 2) Identity Bundle Model

Each session gets an immutable identity bundle for its lifetime unless explicit rotation is triggered.

Bundle fields:

- network identity
  - proxy endpoint, ASN class, country/region
- protocol fingerprint
  - TLS and HTTP signature profile
- browser identity
  - user agent, browser version, platform
- environment identity
  - timezone, locale, language, geolocation
- capability identity
  - fonts, WebGL traits, media support
- behavior identity
  - mimetic profile id for pointer and keyboard style

## 3) Consistency Rules

The allocator enforces coherence checks:

- timezone must match proxy geography
- locale and language must align with region policy
- browser version must match protocol signature family
- hardware capability profile must remain stable across session

## 4) Proxy Pool Management

Proxy pool is segmented by:

- geography
- network type (residential, mobile, datacenter)
- health score
- cost tier

Health scoring dimensions:

- connection success rate
- response latency
- challenge page frequency
- session completion success

## 5) Rotation Policy

Sticky by default. Rotate only when risk threshold is met.

Rotation triggers:

- repeated challenge responses
- sustained network failure
- explicit policy request for geography change

Rotation workflow:

1. checkpoint session state
2. allocate new identity bundle
3. perform warm-up navigation
4. resume task from checkpoint

## 6) Risk Engine

Risk score inputs:

- anomaly in response patterns
- challenge page detections
- rapid interaction rejection rate
- fingerprint inconsistency alerts

Actions by score band:

- low: continue
- medium: reduce interaction intensity and increase verification
- high: rotate identity and escalate policy checks

## 7) Data and Audit

Persist identity and rotation events for reproducibility:

- bundle id and version
- assignment timestamps
- risk score transitions
- trigger reason and outcome

## 8) Guardrails

- deny illegal region-policy combinations
- deny unsupported fingerprint combinations
- limit rotation churn to prevent instability
- enforce authorization and usage policy checks before session creation
