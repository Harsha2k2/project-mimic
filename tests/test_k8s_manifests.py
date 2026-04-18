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
    affinity = deployment["spec"]["template"]["spec"]["affinity"]["nodeAffinity"]
    assert "requiredDuringSchedulingIgnoredDuringExecution" in affinity


def test_keda_scaled_objects_present() -> None:
    docs = _load_docs("deploy/k8s/keda-scalers.yaml")
    names = {doc["metadata"]["name"] for doc in docs}
    assert "mimic-browser-worker-scaler" in names
    assert "mimic-triton-scaler" in names

    browser = next(doc for doc in docs if doc["metadata"]["name"] == "mimic-browser-worker-scaler")
    annotations = browser["metadata"]["annotations"]
    assert annotations["scaling.project-mimic.dev/maxReplicaCount"] == "8"
    assert annotations["scaling.project-mimic.prod/maxReplicaCount"] == "120"


def test_pod_disruption_budgets_present_for_critical_services() -> None:
    docs = _load_docs("deploy/k8s/pod-disruption-budgets.yaml")
    names = {doc["metadata"]["name"] for doc in docs}
    assert "mimic-control-plane-pdb" in names
    assert "mimic-triton-pdb" in names


def test_hpa_manifest_contains_environment_override_annotations() -> None:
    docs = _load_docs("deploy/k8s/hpa.yaml")
    hpa = docs[0]
    assert hpa["kind"] == "HorizontalPodAutoscaler"
    annotations = hpa["metadata"]["annotations"]
    assert annotations["scaling.project-mimic.dev/minReplicas"] == "1"
    assert annotations["scaling.project-mimic.prod/maxReplicas"] == "60"
