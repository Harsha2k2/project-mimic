from pathlib import Path

from tools.deploy.check_manifests import main


def test_deployment_policy_checker_passes_on_repo_manifests(monkeypatch, tmp_path) -> None:
    chart_root = tmp_path / "deploy" / "helm" / "project-mimic"
    chart_root.mkdir(parents=True)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "rendered-helm.yaml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main() == 0


def test_deployment_policy_checker_rejects_latest_tags(monkeypatch, tmp_path) -> None:
    deploy_dir = tmp_path / "deploy" / "k8s"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "broken.yaml").write_text(
        """
        apiVersion: apps/v1
        kind: Deployment
        metadata:
          name: broken
          namespace: project-mimic
        spec:
          template:
            spec:
              containers:
                - name: api
                  image: example/project-mimic:latest
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert main() == 1