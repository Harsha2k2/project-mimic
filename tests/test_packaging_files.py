from pathlib import Path


def test_dockerfile_exists_and_has_entrypoint() -> None:
    dockerfile = Path("Dockerfile")
    assert dockerfile.exists()

    content = dockerfile.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in content
    assert "uvicorn" in content
    assert "project_mimic.api:app" in content


def test_openenv_yaml_exists() -> None:
    assert Path("openenv.yaml").exists()
