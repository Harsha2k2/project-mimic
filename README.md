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

## Deployment Manifests

- `deploy/k8s/` contains namespace, control plane, browser worker, Triton GPU, and KEDA scaler manifests.

## Container Run

```bash
docker build -t project-mimic:local .
docker run --rm -p 8000:8000 project-mimic:local
```
