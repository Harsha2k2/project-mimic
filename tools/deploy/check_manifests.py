from __future__ import annotations

from pathlib import Path
import sys

import yaml


def load_documents(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [doc for doc in yaml.safe_load_all(text) if doc]


def validate_deployment(doc: dict) -> list[str]:
    errors: list[str] = []
    metadata = doc.get("metadata") or {}
    spec = doc.get("spec") or {}
    template = ((spec.get("template") or {}).get("spec") or {})
    containers = template.get("containers") or []

    if not metadata.get("namespace"):
        errors.append(f"{metadata.get('name', 'deployment')}: missing namespace")
    if not containers:
        errors.append(f"{metadata.get('name', 'deployment')}: missing containers")
    for container in containers:
        if not container.get("image"):
            errors.append(f"{metadata.get('name', 'deployment')}: container missing image")
        if str(container.get("image", "")).endswith(":latest"):
            errors.append(f"{metadata.get('name', 'deployment')}: latest tag not allowed")
        security_context = container.get("securityContext") or {}
        if security_context.get("privileged") is True:
            errors.append(f"{metadata.get('name', 'deployment')}: privileged containers not allowed")
    return errors


def validate_canary(doc: dict) -> list[str]:
    errors: list[str] = []
    metadata = doc.get("metadata") or {}
    labels = metadata.get("labels") or {}
    if labels.get("track") != "canary":
        errors.append(f"{metadata.get('name', 'deployment')}: canary deployment missing track=canary label")
    return errors


def validate_control_plane(doc: dict) -> list[str]:
    errors: list[str] = []
    metadata = doc.get("metadata") or {}
    if metadata.get("namespace") != "project-mimic":
        errors.append(f"{metadata.get('name', 'deployment')}: control plane must stay in project-mimic namespace")
    return errors


def validate_triton(doc: dict) -> list[str]:
    errors: list[str] = []
    containers = (((doc.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers") or []
    if not containers:
        errors.append("triton deployment missing containers")
        return errors
    limits = containers[0].get("resources", {}).get("limits", {})
    if limits.get("nvidia.com/gpu") != "1":
        errors.append("triton deployment must request one GPU")
    return errors


def main() -> int:
    errors: list[str] = []

    chart_root = Path("deploy/helm/project-mimic")
    if not chart_root.exists():
        print("Helm chart missing")
        return 1

    for manifest_path in sorted(Path("deploy/k8s").glob("*.yaml")):
        for doc in load_documents(manifest_path):
            kind = doc.get("kind")
            name = (doc.get("metadata") or {}).get("name", manifest_path.name)
            if kind == "Deployment":
                errors.extend(validate_deployment(doc))
                if name == "mimic-control-plane":
                    errors.extend(validate_control_plane(doc))
                if name == "mimic-control-plane-canary":
                    errors.extend(validate_canary(doc))
                if name == "mimic-triton":
                    errors.extend(validate_triton(doc))

    rendered_manifest = Path("artifacts/rendered-helm.yaml")
    if rendered_manifest.exists():
        for doc in load_documents(rendered_manifest):
            if doc.get("kind") == "Deployment":
                errors.extend(validate_deployment(doc))

    if errors:
        for error in errors:
            print(error)
        return 1

    print("Deployment manifests passed policy checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())