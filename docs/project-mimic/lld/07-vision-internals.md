# LLD 07: Vision Internals

## Scope

This document describes vision modules in `src/project_mimic/vision`.

## Core Components

- `TritonVisionClient`: inference transport, retries, circuit breaking, and role filtering.
- `pipeline.py`: OCR normalization, deduplication, confidence thresholds, temporal cache.
- `grounding.py`: entity-to-DOM matching and coordinate resolution.

## Processing Stages

1. Inference request to Triton endpoint.
2. Parse raw entities and normalize OCR text by locale.
3. Deduplicate near-identical entity boxes.
4. Apply role-specific confidence thresholds.
5. Cache stable frame outputs to avoid redundant inference.
6. Ground entities against DOM candidates for action execution.

## Reliability and Security

- Circuit breaker and backoff for transient dependency failures.
- Host allowlist and optional mTLS for outbound inference traffic.
- Redacted error surfaces for token-safe diagnostics.
