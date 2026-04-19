"""Feature flag service for safe progressive rollouts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from typing import Any, Protocol


class FeatureFlagStore(Protocol):
    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        ...

    def load(self) -> dict[str, dict[str, Any]]:
        ...


class InMemoryFeatureFlagStore:
    def __init__(self) -> None:
        self._payload: dict[str, dict[str, Any]] = {}

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._payload = {flag_key: dict(item) for flag_key, item in payload.items()}

    def load(self) -> dict[str, dict[str, Any]]:
        return {flag_key: dict(item) for flag_key, item in self._payload.items()}


class JsonFileFeatureFlagStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, payload: dict[str, dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def load(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}

        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return {}

        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            return {}

        result: dict[str, dict[str, Any]] = {}
        for flag_key, payload in loaded.items():
            if isinstance(flag_key, str) and isinstance(payload, dict):
                result[flag_key] = dict(payload)
        return result


class FeatureFlagService:
    def __init__(self, *, store: FeatureFlagStore | None = None) -> None:
        self._store = store or InMemoryFeatureFlagStore()
        self._flags = self._store.load()

    def upsert(
        self,
        *,
        flag_key: str,
        description: str,
        enabled: bool,
        rollout_percentage: int,
        tenant_allowlist: list[str] | None = None,
        subject_allowlist: list[str] | None = None,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized_key = flag_key.strip()
        if not normalized_key:
            raise ValueError("flag_key must not be empty")
        if rollout_percentage < 0 or rollout_percentage > 100:
            raise ValueError("rollout_percentage must be between 0 and 100")

        now = time.time()
        existing = self._flags.get(normalized_key)
        created_at = now if existing is None else float(existing.get("created_at", now))
        payload = {
            "flag_key": normalized_key,
            "description": description,
            "enabled": bool(enabled),
            "rollout_percentage": int(rollout_percentage),
            "tenant_allowlist": sorted({item.strip() for item in tenant_allowlist or [] if item.strip()}),
            "subject_allowlist": sorted({item.strip() for item in subject_allowlist or [] if item.strip()}),
            "metadata": {str(key): str(value) for key, value in dict(metadata or {}).items()},
            "created_at": created_at,
            "updated_at": now,
        }
        self._flags[normalized_key] = payload
        self._persist()
        return dict(payload)

    def list(self) -> list[dict[str, Any]]:
        return [dict(self._flags[key]) for key in sorted(self._flags.keys())]

    def get(self, *, flag_key: str) -> dict[str, Any]:
        payload = self._flags.get(flag_key)
        if payload is None:
            raise KeyError(flag_key)
        return dict(payload)

    def delete(self, *, flag_key: str) -> dict[str, Any]:
        payload = self._flags.pop(flag_key, None)
        if payload is None:
            raise KeyError(flag_key)
        self._persist()
        return dict(payload)

    def evaluate(
        self,
        *,
        flag_key: str,
        subject_key: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        payload = self.get(flag_key=flag_key)
        normalized_subject = subject_key.strip()
        if not normalized_subject:
            raise ValueError("subject_key must not be empty")

        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        if not bool(payload.get("enabled", False)):
            return {
                "flag_key": payload["flag_key"],
                "subject_key": normalized_subject,
                "tenant_id": normalized_tenant,
                "enabled": False,
                "reason": "flag_disabled",
                "bucket": None,
                "rollout_percentage": int(payload.get("rollout_percentage", 0)),
                "matched_allowlist": False,
                "evaluated_at": time.time(),
            }

        tenant_allowlist = [str(item) for item in payload.get("tenant_allowlist", [])]
        if tenant_allowlist and normalized_tenant not in tenant_allowlist:
            return {
                "flag_key": payload["flag_key"],
                "subject_key": normalized_subject,
                "tenant_id": normalized_tenant,
                "enabled": False,
                "reason": "tenant_not_allowlisted",
                "bucket": None,
                "rollout_percentage": int(payload.get("rollout_percentage", 0)),
                "matched_allowlist": False,
                "evaluated_at": time.time(),
            }

        subject_allowlist = [str(item) for item in payload.get("subject_allowlist", [])]
        if normalized_subject in subject_allowlist:
            return {
                "flag_key": payload["flag_key"],
                "subject_key": normalized_subject,
                "tenant_id": normalized_tenant,
                "enabled": True,
                "reason": "subject_allowlisted",
                "bucket": None,
                "rollout_percentage": int(payload.get("rollout_percentage", 0)),
                "matched_allowlist": True,
                "evaluated_at": time.time(),
            }

        bucket = self._stable_bucket(flag_key=payload["flag_key"], subject_key=normalized_subject)
        rollout_percentage = int(payload.get("rollout_percentage", 0))
        enabled = bucket < rollout_percentage
        reason = "rollout_match" if enabled else "rollout_excluded"
        return {
            "flag_key": payload["flag_key"],
            "subject_key": normalized_subject,
            "tenant_id": normalized_tenant,
            "enabled": enabled,
            "reason": reason,
            "bucket": bucket,
            "rollout_percentage": rollout_percentage,
            "matched_allowlist": False,
            "evaluated_at": time.time(),
        }

    @staticmethod
    def _stable_bucket(*, flag_key: str, subject_key: str) -> int:
        digest = hashlib.sha256(f"{flag_key}:{subject_key}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 100

    def _persist(self) -> None:
        self._store.save(self._flags)
