PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest

.PHONY: setup test test-python test-rust ci

setup:
	/usr/bin/python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e .[dev]

test: test-python test-rust

test-python:
	$(PYTEST)

test-rust:
	cargo test --manifest-path rust/mimetic/Cargo.toml

ci: test
