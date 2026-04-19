"""Workflow marketplace for reusable automation recipes."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4


class WorkflowMarketplaceStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryWorkflowMarketplaceStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFileWorkflowMarketplaceStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}

        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return {}

        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            return {}
        return dict(loaded)


class WorkflowMarketplaceService:
    def __init__(self, *, store: WorkflowMarketplaceStore | None = None) -> None:
        self._store = store or InMemoryWorkflowMarketplaceStore()
        loaded = self._store.load()
        self._recipes: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("recipes", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._installs: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("installs", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._runs: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(loaded.get("runs", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_recipe(
        self,
        *,
        recipe_id: str,
        title: str,
        category: str,
        description: str,
        steps: list[dict[str, Any]],
        tags: list[str] | None = None,
        min_role: str = "operator",
        version: str = "1.0.0",
        published: bool = True,
    ) -> dict[str, Any]:
        normalized_recipe_id = recipe_id.strip().lower()
        if not normalized_recipe_id:
            raise ValueError("recipe_id must not be empty")

        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("title must not be empty")

        normalized_category = category.strip().lower()
        if not normalized_category:
            raise ValueError("category must not be empty")

        normalized_description = description.strip()
        if not normalized_description:
            raise ValueError("description must not be empty")

        normalized_steps: list[dict[str, Any]] = []
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError("steps must contain object payloads")
            action = str(step.get("action", "")).strip().lower()
            if not action:
                raise ValueError("each step requires action")
            normalized_steps.append(
                {
                    "index": index,
                    "action": action,
                    "description": str(step.get("description", "")).strip(),
                    "parameters": {
                        str(key): str(value)
                        for key, value in dict(step.get("parameters", {})).items()
                    },
                }
            )

        if not normalized_steps:
            raise ValueError("steps must not be empty")

        normalized_tags = sorted({item.strip().lower() for item in (tags or []) if item.strip()})
        normalized_min_role = min_role.strip().lower()
        if normalized_min_role not in {"viewer", "operator", "admin"}:
            raise ValueError("min_role must be viewer|operator|admin")

        normalized_version = version.strip()
        if not normalized_version:
            raise ValueError("version must not be empty")

        now = time.time()
        existing = self._recipes.get(normalized_recipe_id)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "recipe_id": normalized_recipe_id,
            "title": normalized_title,
            "category": normalized_category,
            "description": normalized_description,
            "steps": normalized_steps,
            "tags": normalized_tags,
            "min_role": normalized_min_role,
            "version": normalized_version,
            "published": bool(published),
            "created_at": created_at,
            "updated_at": now,
        }
        self._recipes[normalized_recipe_id] = payload
        self._persist()
        return dict(payload)

    def get_recipe(self, *, recipe_id: str) -> dict[str, Any] | None:
        normalized_recipe_id = recipe_id.strip().lower()
        if not normalized_recipe_id:
            raise ValueError("recipe_id must not be empty")
        payload = self._recipes.get(normalized_recipe_id)
        if payload is None:
            return None
        return dict(payload)

    def list_recipes(
        self,
        *,
        category: str | None = None,
        tag: str | None = None,
        include_unpublished: bool = False,
    ) -> list[dict[str, Any]]:
        normalized_category = category.strip().lower() if category is not None else ""
        normalized_tag = tag.strip().lower() if tag is not None else ""

        items = [dict(item) for item in self._recipes.values()]
        if not include_unpublished:
            items = [item for item in items if bool(item.get("published", False))]
        if normalized_category:
            items = [item for item in items if str(item.get("category", "")) == normalized_category]
        if normalized_tag:
            items = [
                item
                for item in items
                if normalized_tag in [str(entry).lower() for entry in item.get("tags", [])]
            ]

        items.sort(key=lambda item: str(item.get("recipe_id", "")))
        return items

    def install_recipe(
        self,
        *,
        tenant_id: str,
        recipe_id: str,
        install_id: str,
        parameters: dict[str, str] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_recipe_id = recipe_id.strip().lower()
        if not normalized_recipe_id:
            raise ValueError("recipe_id must not be empty")

        recipe = self._recipes.get(normalized_recipe_id)
        if recipe is None:
            raise ValueError("recipe not found")

        normalized_install_id = install_id.strip().lower()
        if not normalized_install_id:
            raise ValueError("install_id must not be empty")
        if normalized_install_id in self._installs:
            raise ValueError("install already exists")

        normalized_params = {
            str(key).strip().lower(): str(value).strip()
            for key, value in dict(parameters or {}).items()
            if str(key).strip()
        }

        now = time.time()
        payload = {
            "install_id": normalized_install_id,
            "tenant_id": normalized_tenant,
            "recipe_id": normalized_recipe_id,
            "recipe_version": str(recipe.get("version", "")),
            "parameters": normalized_params,
            "enabled": bool(enabled),
            "created_at": now,
            "updated_at": now,
        }
        self._installs[normalized_install_id] = payload
        self._persist()
        return dict(payload)

    def list_installs(self, *, tenant_id: str, enabled: bool | None = None) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        items: list[dict[str, Any]] = []
        for payload in self._installs.values():
            if str(payload.get("tenant_id", "")) != normalized_tenant:
                continue
            if enabled is not None and bool(payload.get("enabled", False)) != bool(enabled):
                continue
            items.append(dict(payload))

        items.sort(key=lambda item: str(item.get("install_id", "")))
        return items

    def run_install(
        self,
        *,
        tenant_id: str,
        install_id: str,
        initiated_by: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        normalized_install_id = install_id.strip().lower()
        normalized_initiated_by = initiated_by.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if not normalized_install_id:
            raise ValueError("install_id must not be empty")
        if not normalized_initiated_by:
            raise ValueError("initiated_by must not be empty")

        install = self._installs.get(normalized_install_id)
        if install is None:
            raise ValueError("install not found")
        if str(install.get("tenant_id", "")) != normalized_tenant:
            raise ValueError("install does not belong to tenant")
        if not bool(install.get("enabled", False)):
            raise ValueError("install is disabled")

        recipe = self._recipes.get(str(install.get("recipe_id", "")))
        if recipe is None:
            raise ValueError("recipe not found")

        step_results: list[dict[str, Any]] = []
        for step in recipe.get("steps", []):
            if not isinstance(step, dict):
                continue
            step_results.append(
                {
                    "index": int(step.get("index", 0)),
                    "action": str(step.get("action", "")),
                    "status": "simulated" if dry_run else "executed",
                    "description": str(step.get("description", "")),
                }
            )

        now = time.time()
        run_id = f"wmr_{uuid4().hex[:12]}"
        run = {
            "run_id": run_id,
            "tenant_id": normalized_tenant,
            "install_id": normalized_install_id,
            "recipe_id": str(install.get("recipe_id", "")),
            "recipe_version": str(install.get("recipe_version", "")),
            "initiated_by": normalized_initiated_by,
            "dry_run": bool(dry_run),
            "step_results": step_results,
            "status": "completed",
            "started_at": now,
            "finished_at": now,
        }
        self._runs[run_id] = run
        self._trim_runs(limit=5000)
        self._persist()
        return dict(run)

    def list_runs(self, *, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if limit <= 0:
            return []

        items = [
            dict(item)
            for item in self._runs.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        items.sort(key=lambda item: float(item.get("started_at", 0.0)), reverse=True)
        return items[:limit]

    def get_run(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        normalized_run_id = run_id.strip()
        normalized_tenant = tenant_id.strip()
        if not normalized_run_id:
            raise ValueError("run_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        payload = self._runs.get(normalized_run_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    def _trim_runs(self, *, limit: int) -> None:
        if len(self._runs) <= limit:
            return

        items = sorted(
            self._runs.items(),
            key=lambda entry: float(entry[1].get("started_at", 0.0)),
            reverse=True,
        )[:limit]
        self._runs = {key: dict(value) for key, value in items}

    def _persist(self) -> None:
        self._store.save(
            {
                "recipes": self._recipes,
                "installs": self._installs,
                "runs": self._runs,
            }
        )
