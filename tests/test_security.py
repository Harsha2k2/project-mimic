import io
import logging

import pytest

from project_mimic.security import (
    CloudSecretProvider,
    EnvironmentSecretProvider,
    FileSecretProvider,
    MTLSConfig,
    SecretLoader,
    SensitiveDataFilter,
    assert_outbound_host_allowed,
    is_outbound_host_allowed,
    redact_sensitive_structure,
    redact_sensitive_text,
)


class _FakeCloudClient:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def get_secret_value(self, name: str) -> str | None:
        return self.mapping.get(name)


def test_secret_loader_supports_env_file_and_cloud(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PM_TOKEN", "env-secret")
    (tmp_path / "API_KEY").write_text("file-secret", encoding="utf-8")

    loader = SecretLoader(
        [
            EnvironmentSecretProvider(prefix="PM_"),
            FileSecretProvider(str(tmp_path)),
            CloudSecretProvider(_FakeCloudClient({"CLOUD_ONLY": "cloud-secret"})),
        ]
    )

    assert loader.load("TOKEN") == "env-secret"
    assert loader.load("API_KEY") == "file-secret"
    assert loader.load("CLOUD_ONLY") == "cloud-secret"


def test_mtls_config_requires_paths_when_enabled() -> None:
    with pytest.raises(ValueError):
        MTLSConfig(enabled=True)

    cfg = MTLSConfig(
        enabled=True,
        ca_cert_path="/tmp/ca.pem",
        client_cert_path="/tmp/client.pem",
        client_key_path="/tmp/client.key",
    )
    assert cfg.enabled is True


def test_outbound_allowlist_validation() -> None:
    allowlist = {"triton.internal", "svc.cluster.local"}

    assert is_outbound_host_allowed("https://triton.internal/v2/models/x", allowlist) is True
    assert is_outbound_host_allowed("https://foo.svc.cluster.local/health", allowlist) is True
    assert is_outbound_host_allowed("https://evil.example.com", allowlist) is False

    with pytest.raises(ValueError):
        assert_outbound_host_allowed("https://evil.example.com", allowlist)


def test_redaction_masks_tokens_in_text_and_structures() -> None:
    raw = "Bearer abc123 token=mytoken api_key:abc sk-1234567890"
    redacted = redact_sensitive_text(raw)

    assert "abc123" not in redacted
    assert "mytoken" not in redacted
    assert "1234567890" not in redacted

    payload = {
        "Authorization": "Bearer xyz",
        "nested": ["token=abc", {"secret": "sk-abcdef123456"}],
    }
    safe = redact_sensitive_structure(payload)
    dump = str(safe)
    assert "xyz" not in dump
    assert "abc" not in dump
    assert "abcdef123456" not in dump


def test_sensitive_data_filter_prevents_log_leaks() -> None:
    logger = logging.getLogger("project_mimic.security_test")
    logger.setLevel(logging.INFO)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SensitiveDataFilter())

    logger.addHandler(handler)
    try:
        logger.error("failed with Bearer topsecret token=my-token")
    finally:
        logger.removeHandler(handler)

    output = stream.getvalue()
    assert "topsecret" not in output
    assert "my-token" not in output
    assert "[REDACTED]" in output
