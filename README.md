# project-mimic
Distributed vision-based user emulation engine with high-fidelity simulation, orchestrator, and mimetic interaction layer.

## Repository Layout

- `src/project_mimic/`
	- Python package for environment API and orchestration modules.
- `tests/`
	- Unit tests and regression tests.
- `docs/project-mimic/`
	- HLD, LLD, architecture diagrams, and operations docs.
- `.github/workflows/`
	- CI pipelines.
- `WORKFLOW_RULES.md`
	- Commit, testing, and quality discipline for this repository.

## Quickstart

```bash
make setup
make test

# Run baseline scoring (deterministic fallback if env vars are missing)
python inference.py
```

## OpenEnv Metadata

- `openenv.yaml` defines environment metadata, tasks, and runtime variables.
- `inference.py` runs baseline evaluation over easy, medium, and hard tasks.
