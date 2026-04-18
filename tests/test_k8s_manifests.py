from pathlib import Path

import yaml


def _load_docs(path: str) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8")
    return [doc for doc in yaml.safe_load_all(text) if doc]


def test_namespace_manifest_exists() -> None:
    docs = _load_docs("deploy/k8s/namespace.yaml")
    assert docs[0]["kind"] == "Namespace"
    assert docs[0]["metadata"]["name"] == "project-mimic"


def test_control_plane_has_deployment_and_service() -> None:
    docs = _load_docs("deploy/k8s/control-plane.yaml")
    kinds = {doc["kind"] for doc in docs}
    assert "Deployment" in kinds
    assert "Service" in kinds


def test_triton_manifest_requests_gpu() -> None:
    docs = _load_docs("deploy/k8s/triton-inference.yaml")
    deployment = next(doc for doc in docs if doc["kind"] == "Deployment")
    limits = deployment["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]
    assert limits["nvidia.com/gpu"] == "1"


def test_keda_scaled_objects_present() -> None:
    docs = _load_docs("deploy/k8s/keda-scalers.yaml")
    names = {doc["metadata"]["name"] for doc in docs}
    assert "mimic-browser-worker-scaler" in names
    assert "mimic-triton-scaler" in names
