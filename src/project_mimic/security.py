"""Security and secret-management primitives for Project Mimic."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
from typing import Any, Protocol
from urllib.parse import urlparse

from pydantic import model_validator

from .models import ProjectMimicModel


_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[a-z0-9\-\._~\+/]+=*")
_KEY_VALUE_PATTERN = re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+")
_SK_PATTERN = re.compile(r"\bsk-[A-Za-z0-9]{8,}\b")


def redact_sensitive_text(value: str) -> str:
    if not value:
        return value

    redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)

    def _replace_kv(match: re.Match[str]) -> str:
        key = match.group(0).split(":", 1)[0].split("=", 1)[0]
        key = key.strip()
        return f"{key}=[REDACTED]"

    redacted = _KEY_VALUE_PATTERN.sub(_replace_kv, redacted)
    redacted = _SK_PATTERN.sub("[REDACTED_TOKEN]", redacted)
    return redacted


def redact_sensitive_structure(payload: Any) -> Any:
    if isinstance(payload, str):
        return redact_sensitive_text(payload)
    if isinstance(payload, list):
        return [redact_sensitive_structure(item) for item in payload]
    if isinstance(payload, dict):
        return {key: redact_sensitive_structure(value) for key, value in payload.items()}
    return payload


class SensitiveDataFilter(logging.Filter):
    """Logging filter that strips token-like values from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        record.msg = redact_sensitive_text(message)
        record.args = ()
        return True


class SecretProvider(Protocol):
    def get_secret(self, name: str) -> str | None:
        ...


class CloudSecretClient(Protocol):
    def get_secret_value(self, name: str) -> str | None:
        ...


class EnvironmentSecretProvider:
    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix

    def get_secret(self, name: str) -> str | None:
        key = f"{self.prefix}{name}" if self.prefix else name
        return os.getenv(key)


class FileSecretProvider:
    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)

    def get_secret(self, name: str) -> str | None:
        target = self.directory / name
        if not target.exists() or not target.is_file():
            return None
        return target.read_text(encoding="utf-8").strip()


class CloudSecretProvider:
    def __init__(self, client: CloudSecretClient) -> None:
        self.client = client

    def get_secret(self, name: str) -> str | None:
        return self.client.get_secret_value(name)


class SecretLoader:
    """Loads secrets from local env/file sources, then optional cloud provider."""

    def __init__(self, providers: list[SecretProvider]) -> None:
        if not providers:
            raise ValueError("providers must not be empty")
        self.providers = providers

    def load(self, name: str) -> str:
        for provider in self.providers:
            value = provider.get_secret(name)
            if value:
                return value
        raise KeyError(f"secret not found: {name}")


class MTLSConfig(ProjectMimicModel):
    enabled: bool = False
    ca_cert_path: str | None = None
    client_cert_path: str | None = None
    client_key_path: str | None = None
    verify_hostname: bool = True

    @model_validator(mode="after")
    def validate_paths(self) -> "MTLSConfig":
        if not self.enabled:
            return self

        if not self.ca_cert_path:
            raise ValueError("ca_cert_path is required when mTLS is enabled")
        if not self.client_cert_path:
            raise ValueError("client_cert_path is required when mTLS is enabled")
        if not self.client_key_path:
            raise ValueError("client_key_path is required when mTLS is enabled")
        return self


def is_outbound_host_allowed(url: str, allowlist: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False

    normalized = {item.lower() for item in allowlist}
    for allowed in normalized:
        if host == allowed or host.endswith(f".{allowed}"):
            return True
    return False


def assert_outbound_host_allowed(url: str, allowlist: set[str]) -> None:
    if not allowlist:
        return

    if not is_outbound_host_allowed(url, allowlist):
        raise ValueError(f"outbound host not allowed: {url}")
