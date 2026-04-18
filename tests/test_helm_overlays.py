from pathlib import Path

from project_mimic.deploy_overlays import render_overlay


def test_helm_chart_skeleton_exists_for_runtime_components() -> None:
    chart_root = Path("deploy/helm/project-mimic")
    assert (chart_root / "Chart.yaml").exists()
    assert (chart_root / "templates/control-plane-deployment.yaml").exists()
    assert (chart_root / "templates/browser-worker-deployment.yaml").exists()
    assert (chart_root / "templates/triton-deployment.yaml").exists()
    assert (chart_root / "templates/hpa.yaml").exists()
    assert (chart_root / "templates/keda-scaledobjects.yaml").exists()
    assert (chart_root / "templates/pdb.yaml").exists()


def test_overlay_rendering_for_dev_environment() -> None:
    rendered = render_overlay(
        "deploy/helm/project-mimic/values.yaml",
        "deploy/helm/project-mimic/values-dev.yaml",
    )

    assert rendered["controlPlane"]["replicas"] == 1
    assert rendered["browserWorker"]["replicas"] == 2
    assert rendered["triton"]["gpuProfile"] == "spot"
    assert rendered["scaling"]["keda"]["browserWorker"]["maxReplicaCount"] == 8


def test_overlay_rendering_for_prod_environment() -> None:
    rendered = render_overlay(
        "deploy/helm/project-mimic/values.yaml",
        "deploy/helm/project-mimic/values-prod.yaml",
    )

    assert rendered["controlPlane"]["replicas"] == 4
    assert rendered["browserWorker"]["replicas"] == 12
    assert rendered["triton"]["gpuProfile"] == "on-demand"
    assert rendered["scaling"]["hpa"]["maxReplicas"] == 60
    assert rendered["pdb"]["controlPlane"]["minAvailable"] == 2
