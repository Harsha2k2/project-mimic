# Contributor Quickstart

## Prerequisites

- Python 3.12+
- Rust stable toolchain
- Docker (optional for container checks)

## Local Setup

1. Install dependencies:
   - `python -m pip install -e .[dev]`
2. Run Python tests:
   - `pytest -q`
3. Run Rust tests:
   - `cargo test --manifest-path rust/mimetic/Cargo.toml`

## Local Runbook

1. Start API locally:
   - `uvicorn project_mimic.api:app --host 0.0.0.0 --port 8000`
2. Run deterministic inference:
   - `python inference.py`
3. Run benchmark report:
   - `python benchmark.py --seed 42 --history-file artifacts/score_trend_history.json`

## Feature Workflow

1. Pick next unchecked block in `PROJECT_TODO_100.md`.
2. Implement code and tests.
3. Run Python and Rust suites.
4. Commit one feature at a time.
