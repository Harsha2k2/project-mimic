"""Audit export sinks for SIEM delivery targets."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class AuditExportSink(Protocol):
    def export(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        ...


class FileAuditExportSink:
    def __init__(self, path: str) -> None:
        if not path.strip():
            raise ValueError("path must not be empty")
        self._path = Path(path)

    def export(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, sort_keys=True))
                handle.write("\n")
        return {
            "destination": "file",
            "path": str(self._path),
            "exported": len(events),
        }


class WebhookAuditExportSink:
    def __init__(self, url: str, timeout_seconds: float = 5.0) -> None:
        if not url.strip():
            raise ValueError("url must not be empty")
        self._url = url
        self._timeout_seconds = timeout_seconds

    def export(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests package is required for webhook audit export") from exc

        response = requests.post(
            self._url,
            json={"events": events},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return {
            "destination": "webhook",
            "url": self._url,
            "exported": len(events),
            "status_code": response.status_code,
        }


def build_audit_export_sink_from_env() -> AuditExportSink | None:
    destination = os.getenv("AUDIT_EXPORT_DESTINATION", "").strip().lower()
    if destination == "file":
        file_path = os.getenv("AUDIT_EXPORT_FILE_PATH", "").strip()
        if not file_path:
            raise ValueError("AUDIT_EXPORT_FILE_PATH must be set when destination=file")
        return FileAuditExportSink(file_path)
    if destination == "webhook":
        webhook_url = os.getenv("AUDIT_EXPORT_WEBHOOK_URL", "").strip()
        if not webhook_url:
            raise ValueError("AUDIT_EXPORT_WEBHOOK_URL must be set when destination=webhook")
        timeout = float(os.getenv("AUDIT_EXPORT_WEBHOOK_TIMEOUT_SECONDS", "5"))
        return WebhookAuditExportSink(webhook_url, timeout_seconds=timeout)
    return None
