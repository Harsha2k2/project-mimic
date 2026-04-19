"""Pluggable site-pack registry for strategy packaging and versioning."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any, Protocol

SITE_PACK_CHANNELS = ("dev", "canary", "prod")


class SitePackRegistryStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any] | None:
        ...


class InMemorySitePackRegistryStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] | None = None

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = dict(payload)

    def load(self) -> dict[str, Any] | None:
        return dict(self._payload) if self._payload is not None else None


class JsonFileSitePackRegistryStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None

        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return None

        loaded = json.loads(content)
        return loaded if isinstance(loaded, dict) else None


class SitePackRegistry:
    def __init__(self, *, store: SitePackRegistryStore | None = None) -> None:
        self._store = store or InMemorySitePackRegistryStore()
        self._versions: dict[str, dict[str, Any]] = {}
        self._channels: dict[str, dict[str, Any] | None] = {channel: None for channel in SITE_PACK_CHANNELS}
        self._restore()

    def register_version(
        self,
        *,
        pack_id: str,
        version: str,
        strategy_class: str,
        artifact_uri: str,
        site_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cleaned_pack_id = pack_id.strip()
        cleaned_version = version.strip()
        cleaned_strategy_class = strategy_class.strip()
        cleaned_artifact_uri = artifact_uri.strip()

        if not cleaned_pack_id:
            raise ValueError("pack_id must not be empty")
        if not cleaned_version:
            raise ValueError("version must not be empty")
        if not cleaned_strategy_class:
            raise ValueError("strategy_class must not be empty")
        if not cleaned_artifact_uri:
            raise ValueError("artifact_uri must not be empty")

        resolved_site_ids = sorted({item.strip() for item in (site_ids or []) if item.strip()})
        if not resolved_site_ids:
            resolved_site_ids = [cleaned_pack_id]

        key = self._version_key(cleaned_pack_id, cleaned_version)
        if key in self._versions:
            raise ValueError("site pack version already registered")

        payload = {
            "pack_id": cleaned_pack_id,
            "version": cleaned_version,
            "strategy_class": cleaned_strategy_class,
            "artifact_uri": cleaned_artifact_uri,
            "site_ids": resolved_site_ids,
            "metadata": dict(metadata or {}),
            "created_at": time.time(),
        }
        self._versions[key] = payload
        self._persist()
        return dict(payload)

    def list_versions(self, *, pack_id: str | None = None) -> list[dict[str, Any]]:
        items = list(self._versions.values())
        if pack_id is not None:
            items = [item for item in items if item.get("pack_id") == pack_id]
        items.sort(key=lambda item: float(item.get("created_at", 0.0)), reverse=False)
        return [dict(item) for item in items]

    def promote(self, *, channel: str, pack_id: str, version: str) -> dict[str, Any]:
        normalized_channel = channel.strip().lower()
        if normalized_channel not in SITE_PACK_CHANNELS:
            raise ValueError(f"unsupported channel: {channel}")

        key = self._version_key(pack_id.strip(), version.strip())
        payload = self._versions.get(key)
        if payload is None:
            raise KeyError(key)

        assignment = {
            "channel": normalized_channel,
            "pack_id": payload["pack_id"],
            "version": payload["version"],
            "strategy_class": payload["strategy_class"],
            "artifact_uri": payload["artifact_uri"],
            "site_ids": [str(item) for item in payload.get("site_ids", []) if isinstance(item, str)],
            "updated_at": time.time(),
        }
        self._channels[normalized_channel] = assignment
        self._persist()
        return dict(assignment)

    def list_channels(self) -> dict[str, dict[str, Any] | None]:
        return {
            channel: dict(payload) if payload is not None else None
            for channel, payload in self._channels.items()
        }

    def _persist(self) -> None:
        self._store.save(
            {
                "versions": dict(self._versions),
                "channels": {
                    channel: dict(payload) if payload is not None else None
                    for channel, payload in self._channels.items()
                },
            }
        )

    def _restore(self) -> None:
        payload = self._store.load()
        if not payload:
            return

        versions_payload = payload.get("versions", {})
        channels_payload = payload.get("channels", {})

        if isinstance(versions_payload, dict):
            for key, entry in versions_payload.items():
                if isinstance(key, str) and isinstance(entry, dict):
                    self._versions[key] = dict(entry)

        if isinstance(channels_payload, dict):
            for channel in SITE_PACK_CHANNELS:
                assignment = channels_payload.get(channel)
                if isinstance(assignment, dict):
                    self._channels[channel] = dict(assignment)

    @staticmethod
    def _version_key(pack_id: str, version: str) -> str:
        return f"{pack_id}::{version}"
