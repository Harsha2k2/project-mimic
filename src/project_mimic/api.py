"""FastAPI service for Project Mimic environment sessions."""

from __future__ import annotations

import asyncio
import json
from enum import Enum
import os
from threading import Event, Thread
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import ConfigDict, Field

from .error_mapping import map_exception_to_error
from .audit_export import build_audit_export_sink_from_env
from .drift_detection import DriftMonitor
from .engine import ExecutionEngine
from .event_stream import EventStreamBroker
from .model_registry import InMemoryModelRegistryStore, JsonFileModelRegistryStore, ModelRegistry
from .models import Observation, ProjectMimicModel, Reward, UIAction
from .observability import InMemoryMetrics, OpenTelemetryTracer
from .queue_runtime import ActionJob, InMemoryActionQueue, JsonFileQueueStore
from .review_queue import HumanReviewQueue, InMemoryReviewQueueStore, JsonFileReviewQueueStore
from .security import redact_sensitive_structure, redact_sensitive_text
from .orchestrator.decision_orchestrator import DecisionOrchestrator
from .session_lifecycle import (
    InMemorySessionMetadataStore,
    InvalidSessionTransitionError,
    JsonFileSessionMetadataStore,
    SessionAccessDeniedError,
    SessionExpiredError,
    SessionRegistry,
    SessionStatus,
)
from .webhooks import (
    InMemoryWebhookSubscriptionStore,
    JsonFileWebhookSubscriptionStore,
    LifecycleEventWebhookPublisher,
)
from .vision.grounding import BBox, DOMNode, UIEntity


class APIPayloadModel(ProjectMimicModel):
    schema_version: str = "1.0"


class CreateSessionRequest(APIPayloadModel):
    goal: str
    max_steps: int = Field(default=20, ge=1)


class ResetSessionRequest(APIPayloadModel):
    goal: str | None = None


class SessionCreatedResponse(APIPayloadModel):
    session_id: str
    observation: Observation


class StepResponse(APIPayloadModel):
    observation: Observation
    reward: Reward
    done: bool
    info: dict[str, Any]


class SessionListResponse(APIPayloadModel):
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total: int
    sort_by: str
    sort_order: str
    filters: dict[str, Any]


class BBoxPayload(APIPayloadModel):
    x: int
    y: int
    width: int
    height: int


class UIEntityPayload(APIPayloadModel):
    entity_id: str
    label: str
    role: str
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BBoxPayload


class DOMNodePayload(APIPayloadModel):
    dom_node_id: str
    role: str
    text: str
    visible: bool
    enabled: bool
    z_index: int
    bbox: BBoxPayload


class DecideRequest(APIPayloadModel):
    entities: list[UIEntityPayload]
    dom_nodes: list[DOMNodePayload]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "entities": [
                    {
                        "entity_id": "e1",
                        "label": "Search",
                        "role": "button",
                        "text": "Search Flights",
                        "confidence": 0.91,
                        "bbox": {"x": 100, "y": 100, "width": 120, "height": 40},
                    }
                ],
                "dom_nodes": [
                    {
                        "dom_node_id": "search-btn",
                        "role": "button",
                        "text": "Search Flights",
                        "visible": True,
                        "enabled": True,
                        "z_index": 10,
                        "bbox": {"x": 102, "y": 101, "width": 120, "height": 40},
                    }
                ],
            }
        }
    )


class DecideResponse(APIPayloadModel):
    status: str
    state: str
    dom_node_id: str | None = None
    x: int | None = None
    y: int | None = None
    score: float | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "ok",
                "state": "complete",
                "dom_node_id": "search-btn",
                "x": 162,
                "y": 121,
                "score": 0.93,
            }
        }
    )


class APIErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    REQUEST_VALIDATION_ERROR = "REQUEST_VALIDATION_ERROR"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    SESSION_CONFLICT = "SESSION_CONFLICT"
    API_DEPRECATED = "API_DEPRECATED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class APIError(APIPayloadModel):
    code: str
    message: str
    correlation_id: str | None = None
    details: list[dict[str, Any]] = Field(default_factory=list)


class APIErrorResponse(APIPayloadModel):
    error: APIError


class DeprecationPolicyResponse(APIPayloadModel):
    replacement_prefix: str
    deprecated_prefix: str
    sunset: str
    policy: str


class APIKeyMetadata(APIPayloadModel):
    key_id: str
    role: str
    tenant_id: str
    scopes: list[str]
    active: bool
    created_at: float
    last_rotated_at: float | None = None


class APIKeyListResponse(APIPayloadModel):
    items: list[APIKeyMetadata]


class APIKeyCreateRequest(APIPayloadModel):
    role: str = "operator"
    tenant_id: str = "default"
    scopes: list[str] = Field(default_factory=list)


class APIKeyCreateResponse(APIPayloadModel):
    key_id: str
    api_key: str
    role: str
    tenant_id: str
    scopes: list[str]


class APIKeyRotateResponse(APIPayloadModel):
    key_id: str
    api_key: str
    rotated_at: float


class APIKeyRevokeResponse(APIPayloadModel):
    key_id: str
    revoked: bool


class AuditLogEntry(APIPayloadModel):
    event_id: str
    timestamp: float
    request_id: str | None = None
    tenant_id: str
    api_key_id: str | None = None
    action: str
    resource_type: str
    resource_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class AuditLogListResponse(APIPayloadModel):
    items: list[AuditLogEntry]
    total: int


class AuditExportResponse(APIPayloadModel):
    exported: int
    destination: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebhookSubscriptionCreateRequest(APIPayloadModel):
    name: str
    callback_url: str
    events: list[str] = Field(default_factory=list)
    secret: str | None = None


class WebhookSubscriptionResponse(APIPayloadModel):
    subscription_id: str
    name: str
    callback_url: str
    events: list[str] = Field(default_factory=list)
    tenant_id: str
    active: bool
    created_at: float
    updated_at: float


class WebhookSubscriptionListResponse(APIPayloadModel):
    items: list[WebhookSubscriptionResponse]
    total: int


class AsyncJobSubmitRequest(APIPayloadModel):
    job_type: str
    input: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class AsyncJobResponse(APIPayloadModel):
    job_id: str
    idempotency_key: str
    status: str
    action_payload: dict[str, Any] = Field(default_factory=dict)
    attempts: int
    max_attempts: int
    created_at: float
    updated_at: float
    lease_worker_id: str | None = None
    lease_expires_at: float | None = None
    last_error: str | None = None


class AsyncJobSubmitResponse(APIPayloadModel):
    job: AsyncJobResponse


class AsyncJobCancelResponse(APIPayloadModel):
    canceled: bool
    job: AsyncJobResponse


class ModelRegisterRequest(APIPayloadModel):
    model_id: str
    version: str
    artifact_uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelVersionListResponse(APIPayloadModel):
    items: list[dict[str, Any]]
    total: int


class ModelPromotionRequest(APIPayloadModel):
    model_id: str
    version: str


class ModelPromotionResponse(APIPayloadModel):
    assignment: dict[str, Any]


class ModelChannelListResponse(APIPayloadModel):
    channels: dict[str, dict[str, Any] | None]


class DriftSampleRequest(APIPayloadModel):
    stream_id: str
    metric_name: str
    value: float
    threshold: float | None = None


class DriftStatusResponse(APIPayloadModel):
    stream_id: str
    metric_name: str
    baseline_mean: float
    baseline_samples: int
    recent_mean: float | None = None
    recent_sample_count: int
    drift_score: float
    threshold: float
    alert_active: bool
    updated_at: float


class DriftAlertListResponse(APIPayloadModel):
    items: list[DriftStatusResponse]
    total: int


class ReviewQueueSubmitRequest(APIPayloadModel):
    session_id: str | None = None
    action_payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class ReviewQueueResolveRequest(APIPayloadModel):
    decision: str
    note: str | None = None


class ReviewQueueItemResponse(APIPayloadModel):
    review_id: str
    tenant_id: str
    session_id: str | None = None
    action_payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float
    reason: str
    status: str
    resolution: str | None = None
    resolution_note: str | None = None
    created_at: float
    resolved_at: float | None = None


class ReviewQueueListResponse(APIPayloadModel):
    items: list[ReviewQueueItemResponse]
    total: int


API_V1_PREFIX = "/api/v1"
LEGACY_PREFIX = ""
LEGACY_SUNSET_DATE = "2026-06-30"
DEPRECATION_DOC_PATH = f"{API_V1_PREFIX}/deprecations"


def create_app() -> FastAPI:
    app = FastAPI(title="Project Mimic API", version="0.1.0")
    session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
    scavenger_interval_seconds = int(os.getenv("SESSION_SCAVENGER_INTERVAL_SECONDS", "5"))
    bootstrap_auth_keys = [item.strip() for item in os.getenv("API_AUTH_KEYS", "").split(",") if item.strip()]
    role_rank = {"viewer": 1, "operator": 2, "admin": 3}
    default_role = os.getenv("API_AUTH_DEFAULT_ROLE", "operator").strip().lower()
    if default_role not in role_rank:
        default_role = "operator"
    default_tenant = os.getenv("API_DEFAULT_TENANT", "default").strip() or "default"
    tenant_enforcement = os.getenv("API_TENANT_ENFORCEMENT", "true").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    cors_allow_origins = [item.strip() for item in os.getenv("API_CORS_ALLOW_ORIGINS", "").split(",") if item.strip()]
    cors_allow_credentials = os.getenv("API_CORS_ALLOW_CREDENTIALS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    cors_allow_methods = [
        item.strip().upper()
        for item in os.getenv("API_CORS_ALLOW_METHODS", "GET,POST,PUT,PATCH,DELETE,OPTIONS").split(",")
        if item.strip()
    ]
    cors_allow_headers = [
        item.strip()
        for item in os.getenv(
            "API_CORS_ALLOW_HEADERS",
            "Authorization,Content-Type,X-API-Key,X-Request-ID,X-Tenant-ID",
        ).split(",")
        if item.strip()
    ]
    rate_limit_per_minute = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "0"))
    daily_quota = int(os.getenv("API_DAILY_QUOTA", "0"))
    max_request_body_bytes = int(os.getenv("API_MAX_REQUEST_BODY_BYTES", "0"))
    request_timeout_seconds = float(os.getenv("API_REQUEST_TIMEOUT_SECONDS", "0"))
    tenant_minute_counters: dict[tuple[str, int], int] = {}
    tenant_daily_counters: dict[tuple[str, int], int] = {}
    audit_events: list[dict[str, Any]] = []
    metadata_store_type = os.getenv("SESSION_METADATA_STORE", "memory").strip().lower()
    metadata_store_file_path = os.getenv("SESSION_METADATA_FILE_PATH", "")
    async_job_queue_store_type = os.getenv("ASYNC_JOB_QUEUE_STORE", "memory").strip().lower()
    async_job_queue_file_path = os.getenv("ASYNC_JOB_QUEUE_FILE_PATH", "")
    async_job_idempotency_ttl_seconds = int(os.getenv("ASYNC_JOB_IDEMPOTENCY_TTL_SECONDS", "3600"))
    model_registry_store_type = os.getenv("MODEL_REGISTRY_STORE", "memory").strip().lower()
    model_registry_file_path = os.getenv("MODEL_REGISTRY_FILE_PATH", "")
    drift_baseline_window = int(os.getenv("DRIFT_BASELINE_WINDOW", "20"))
    drift_recent_window = int(os.getenv("DRIFT_RECENT_WINDOW", "10"))
    drift_default_threshold = float(os.getenv("DRIFT_DEFAULT_THRESHOLD", "0.25"))
    review_queue_store_type = os.getenv("REVIEW_QUEUE_STORE", "memory").strip().lower()
    review_queue_file_path = os.getenv("REVIEW_QUEUE_FILE_PATH", "")
    event_stream_max_events = int(os.getenv("EVENT_STREAM_MAX_EVENTS", "1000"))
    webhook_store_type = os.getenv("WEBHOOK_SUBSCRIPTION_STORE", "memory").strip().lower()
    webhook_store_file_path = os.getenv("WEBHOOK_SUBSCRIPTION_FILE_PATH", "")
    webhook_timeout_seconds = float(os.getenv("WEBHOOK_DELIVERY_TIMEOUT_SECONDS", "3"))
    operator_artifacts_file_path = os.getenv("OPERATOR_CONSOLE_ARTIFACTS_FILE_PATH", "")
    operator_queue_file_path = os.getenv("OPERATOR_CONSOLE_QUEUE_FILE_PATH", "")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins,
        allow_credentials=cors_allow_credentials,
        allow_methods=cors_allow_methods,
        allow_headers=cors_allow_headers,
    )

    role_map: dict[str, str] = {}
    for pair in os.getenv("API_AUTH_ROLE_MAP", "").split(","):
        cleaned = pair.strip()
        if not cleaned or ":" not in cleaned:
            continue
        key, role = cleaned.split(":", 1)
        key = key.strip()
        role = role.strip().lower()
        if key and role in role_rank:
            role_map[key] = role

    tenant_map: dict[str, str] = {}
    for pair in os.getenv("API_AUTH_TENANT_MAP", "").split(","):
        cleaned = pair.strip()
        if not cleaned or ":" not in cleaned:
            continue
        key, tenant = cleaned.split(":", 1)
        key = key.strip()
        tenant = tenant.strip()
        if key and tenant:
            tenant_map[key] = tenant

    scope_map: dict[str, list[str]] = {}
    for pair in os.getenv("API_AUTH_SCOPE_MAP", "").split(","):
        cleaned = pair.strip()
        if not cleaned or ":" not in cleaned:
            continue
        key, scope_text = cleaned.split(":", 1)
        key = key.strip()
        scopes = [scope.strip() for scope in scope_text.split("|") if scope.strip()]
        if key:
            scope_map[key] = scopes

    api_key_records_by_id: dict[str, dict[str, Any]] = {}
    key_id_by_secret: dict[str, str] = {}

    def _register_api_key(
        *,
        secret: str,
        role: str,
        tenant_id: str,
        scopes: list[str],
        key_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_role = role.strip().lower()
        if resolved_role not in role_rank:
            raise ValueError("invalid role")
        resolved_tenant = tenant_id.strip() or default_tenant
        now = time.time()
        resolved_key_id = key_id or f"key_{uuid4().hex[:12]}"
        record = {
            "key_id": resolved_key_id,
            "role": resolved_role,
            "tenant_id": resolved_tenant,
            "scopes": list(scopes),
            "active": True,
            "created_at": now,
            "last_rotated_at": None,
        }
        api_key_records_by_id[resolved_key_id] = record
        key_id_by_secret[secret] = resolved_key_id
        return record

    for index, secret in enumerate(bootstrap_auth_keys, start=1):
        _register_api_key(
            secret=secret,
            role=role_map.get(secret, default_role),
            tenant_id=tenant_map.get(secret, default_tenant),
            scopes=scope_map.get(secret, []),
            key_id=f"bootstrap-{index}",
        )

    def _lookup_active_key(secret: str) -> dict[str, Any] | None:
        key_id = key_id_by_secret.get(secret)
        if key_id is None:
            return None
        record = api_key_records_by_id.get(key_id)
        if record is None or not bool(record.get("active", False)):
            return None
        return record

    if metadata_store_type == "file":
        if not metadata_store_file_path:
            raise RuntimeError("SESSION_METADATA_FILE_PATH is required when SESSION_METADATA_STORE=file")
        metadata_store = JsonFileSessionMetadataStore(metadata_store_file_path)
    else:
        metadata_store = InMemorySessionMetadataStore()

    if async_job_queue_store_type == "file":
        if not async_job_queue_file_path:
            raise RuntimeError("ASYNC_JOB_QUEUE_FILE_PATH is required when ASYNC_JOB_QUEUE_STORE=file")
        async_job_queue_store = JsonFileQueueStore(async_job_queue_file_path)
    else:
        async_job_queue_store = None

    if model_registry_store_type == "file":
        if not model_registry_file_path:
            raise RuntimeError("MODEL_REGISTRY_FILE_PATH is required when MODEL_REGISTRY_STORE=file")
        model_registry_store = JsonFileModelRegistryStore(model_registry_file_path)
    else:
        model_registry_store = InMemoryModelRegistryStore()

    if review_queue_store_type == "file":
        if not review_queue_file_path:
            raise RuntimeError("REVIEW_QUEUE_FILE_PATH is required when REVIEW_QUEUE_STORE=file")
        review_queue_store = JsonFileReviewQueueStore(review_queue_file_path)
    else:
        review_queue_store = InMemoryReviewQueueStore()

    if webhook_store_type == "file":
        if not webhook_store_file_path:
            raise RuntimeError("WEBHOOK_SUBSCRIPTION_FILE_PATH is required when WEBHOOK_SUBSCRIPTION_STORE=file")
        webhook_store = JsonFileWebhookSubscriptionStore(webhook_store_file_path)
    else:
        webhook_store = InMemoryWebhookSubscriptionStore()

    registry = SessionRegistry(ttl_seconds=session_ttl_seconds, metadata_store=metadata_store)
    async_job_queue = InMemoryActionQueue(
        store=async_job_queue_store,
        idempotency_ttl_seconds=async_job_idempotency_ttl_seconds,
    )
    model_registry = ModelRegistry(store=model_registry_store)
    drift_monitor = DriftMonitor(
        baseline_window=drift_baseline_window,
        recent_window=drift_recent_window,
        default_threshold=drift_default_threshold,
    )
    review_queue = HumanReviewQueue(store=review_queue_store)
    event_broker = EventStreamBroker(max_events=event_stream_max_events)
    api_tracer = OpenTelemetryTracer(component="api")
    orchestrator_tracer = OpenTelemetryTracer(component="orchestrator")
    audit_sink = build_audit_export_sink_from_env()
    webhook_publisher = LifecycleEventWebhookPublisher(store=webhook_store, timeout_seconds=webhook_timeout_seconds)
    engine = ExecutionEngine(orchestrator=DecisionOrchestrator(tracer=orchestrator_tracer))
    metrics = InMemoryMetrics()
    scavenger_stop = Event()
    scavenger_thread: Thread | None = None

    def _set_deprecation_headers(response: Response) -> None:
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = LEGACY_SUNSET_DATE
        response.headers["Link"] = f"<{DEPRECATION_DOC_PATH}>; rel=\"deprecation\""

    def _is_auth_exempt_path(path: str) -> bool:
        if path in {"/openapi.json", "/docs/oauth2-redirect"}:
            return True
        return path.startswith("/docs") or path == "/redoc"

    def _required_role_for_request(method: str, path: str) -> str:
        if path.startswith(f"{API_V1_PREFIX}/operator") or path.startswith("/operator"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/events/subscriptions") or path.startswith("/events/subscriptions"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/models/registry") or path.startswith("/models/registry"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/auth/keys") or path.startswith("/auth/keys"):
            return "admin"
        if (
            path.startswith(f"{API_V1_PREFIX}/audit/logs")
            or path.startswith("/audit/logs")
            or path.startswith(f"{API_V1_PREFIX}/audit/export")
            or path.startswith("/audit/export")
        ):
            return "admin"
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            return "operator"
        return "viewer"

    def _tenant_id(request: Request) -> str:
        return str(getattr(request.state, "tenant_id", default_tenant))

    def _append_audit_event(
        request: Request,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        audit_events.append(
            {
                "event_id": str(uuid4()),
                "timestamp": time.time(),
                "request_id": getattr(request.state, "request_id", None),
                "tenant_id": _tenant_id(request),
                "api_key_id": getattr(request.state, "api_key_id", None),
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "details": details or {},
            }
        )

    def _emit_lifecycle_event(
        request: Request,
        *,
        event_type: str,
        session_id: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "session_id": session_id,
            "request_id": getattr(request.state, "request_id", None),
            "details": details or {},
        }
        tenant_id = _tenant_id(request)
        _publish_realtime_event(event_type=event_type, tenant_id=tenant_id, payload=payload)
        try:
            webhook_publisher.emit(event_type=event_type, tenant_id=tenant_id, payload=payload)
        except Exception:
            # Lifecycle operations must remain available even if webhook delivery fails.
            return

    def _publish_realtime_event(
        *,
        event_type: str,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> None:
        try:
            event_broker.publish(event_type=event_type, tenant_id=tenant_id, payload=payload)
        except Exception:
            # Event streaming is best-effort and should not break primary operations.
            return

    def _format_sse_events(events: list[dict[str, Any]]) -> str:
        if not events:
            return ": keepalive\n\n"

        chunks: list[str] = []
        for event in events:
            sequence = int(event.get("sequence", 0))
            event_type = str(event.get("event_type", "message"))
            chunks.append(f"id: {sequence}\n")
            chunks.append(f"event: {event_type}\n")
            chunks.append(f"data: {json.dumps(event, sort_keys=True)}\n\n")
        return "".join(chunks)

    def _build_event_stream_response(
        *,
        tenant_id: str,
        after_id: int,
        max_events: int,
        wait_seconds: float,
        event_type: str | None,
    ) -> StreamingResponse:
        events = event_broker.list_events(
            after_id=after_id,
            tenant_id=tenant_id,
            max_events=max_events,
            event_type=event_type,
        )
        if not events and wait_seconds > 0:
            event_broker.wait_for_new_events(after_id=after_id, timeout_seconds=wait_seconds)
            events = event_broker.list_events(
                after_id=after_id,
                tenant_id=tenant_id,
                max_events=max_events,
                event_type=event_type,
            )

        body = _format_sse_events(events)
        response = StreamingResponse(iter([body]), media_type="text/event-stream")
        response.headers["Cache-Control"] = "no-cache"
        return response

    def _to_webhook_subscription_response(payload: dict[str, Any]) -> WebhookSubscriptionResponse:
        return WebhookSubscriptionResponse(
            subscription_id=str(payload.get("subscription_id", "")),
            name=str(payload.get("name", "")),
            callback_url=str(payload.get("callback_url", "")),
            events=[str(item) for item in payload.get("events", []) if isinstance(item, str)],
            tenant_id=str(payload.get("tenant_id", default_tenant)),
            active=bool(payload.get("active", True)),
            created_at=float(payload.get("created_at", time.time())),
            updated_at=float(payload.get("updated_at", time.time())),
        )

    def _to_async_job_response(job: ActionJob) -> AsyncJobResponse:
        return AsyncJobResponse(
            job_id=job.job_id,
            idempotency_key=job.idempotency_key,
            status=job.status.value,
            action_payload=dict(job.action_payload),
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            created_at=job.created_at,
            updated_at=job.updated_at,
            lease_worker_id=job.lease_worker_id,
            lease_expires_at=job.lease_expires_at,
            last_error=job.last_error,
        )

    def _submit_async_job(payload: AsyncJobSubmitRequest) -> AsyncJobSubmitResponse:
        idempotency_key = payload.idempotency_key.strip() if payload.idempotency_key else ""
        if not idempotency_key:
            idempotency_key = f"job-{uuid4().hex}"

        job = async_job_queue.dispatch(
            {
                "job_type": payload.job_type,
                "input": payload.input,
            },
            idempotency_key=idempotency_key,
        )
        return AsyncJobSubmitResponse(job=_to_async_job_response(job))

    def _get_async_job(job_id: str) -> AsyncJobResponse:
        try:
            job = async_job_queue.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"job not found: {job_id}") from exc
        return _to_async_job_response(job)

    def _cancel_async_job(job_id: str) -> AsyncJobCancelResponse:
        try:
            job = async_job_queue.cancel(job_id, reason="canceled via api")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"job not found: {job_id}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return AsyncJobCancelResponse(canceled=True, job=_to_async_job_response(job))

    def _register_model_version(payload: ModelRegisterRequest) -> dict[str, Any]:
        try:
            return model_registry.register_version(
                model_id=payload.model_id,
                version=payload.version,
                artifact_uri=payload.artifact_uri,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _list_model_versions(model_id: str | None = None) -> ModelVersionListResponse:
        items = model_registry.list_versions(model_id=model_id)
        return ModelVersionListResponse(items=items, total=len(items))

    def _promote_model_channel(channel: str, payload: ModelPromotionRequest) -> ModelPromotionResponse:
        try:
            assignment = model_registry.promote(
                channel=channel,
                model_id=payload.model_id,
                version=payload.version,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="model version is not registered") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ModelPromotionResponse(assignment=assignment)

    def _to_drift_status_response(payload: dict[str, Any]) -> DriftStatusResponse:
        return DriftStatusResponse(
            stream_id=str(payload.get("stream_id", "")),
            metric_name=str(payload.get("metric_name", "")),
            baseline_mean=float(payload.get("baseline_mean", 0.0)),
            baseline_samples=int(payload.get("baseline_samples", 0)),
            recent_mean=(
                None
                if payload.get("recent_mean") is None
                else float(payload.get("recent_mean"))
            ),
            recent_sample_count=int(payload.get("recent_sample_count", 0)),
            drift_score=float(payload.get("drift_score", 0.0)),
            threshold=float(payload.get("threshold", drift_default_threshold)),
            alert_active=bool(payload.get("alert_active", False)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _record_drift_sample(payload: DriftSampleRequest) -> DriftStatusResponse:
        try:
            status = drift_monitor.ingest(
                stream_id=payload.stream_id,
                metric_name=payload.metric_name,
                value=payload.value,
                threshold=payload.threshold,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_drift_status_response(status)

    def _drift_status(stream_id: str, metric_name: str) -> DriftStatusResponse:
        status = drift_monitor.status(stream_id=stream_id, metric_name=metric_name)
        if status is None:
            raise HTTPException(status_code=404, detail="drift metric not found")
        return _to_drift_status_response(status)

    def _list_drift_alerts() -> DriftAlertListResponse:
        items = [_to_drift_status_response(payload) for payload in drift_monitor.active_alerts()]
        return DriftAlertListResponse(items=items, total=len(items))

    def _to_review_queue_item_response(payload: dict[str, Any]) -> ReviewQueueItemResponse:
        return ReviewQueueItemResponse(
            review_id=str(payload.get("review_id", "")),
            tenant_id=str(payload.get("tenant_id", default_tenant)),
            session_id=(
                None
                if payload.get("session_id") is None
                else str(payload.get("session_id"))
            ),
            action_payload=dict(payload.get("action_payload", {})),
            confidence=float(payload.get("confidence", 0.0)),
            reason=str(payload.get("reason", "")),
            status=str(payload.get("status", "pending")),
            resolution=(
                None
                if payload.get("resolution") is None
                else str(payload.get("resolution"))
            ),
            resolution_note=(
                None
                if payload.get("resolution_note") is None
                else str(payload.get("resolution_note"))
            ),
            created_at=float(payload.get("created_at", 0.0)),
            resolved_at=(
                None
                if payload.get("resolved_at") is None
                else float(payload.get("resolved_at"))
            ),
        )

    def _submit_review_queue_item(
        payload: ReviewQueueSubmitRequest,
        *,
        tenant_id: str,
    ) -> ReviewQueueItemResponse:
        try:
            item = review_queue.submit(
                tenant_id=tenant_id,
                action_payload=payload.action_payload,
                confidence=payload.confidence,
                reason=payload.reason,
                session_id=payload.session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_review_queue_item_response(item)

    def _list_review_queue_items(
        *,
        tenant_id: str,
        status: str | None,
        limit: int,
    ) -> ReviewQueueListResponse:
        items = review_queue.list(tenant_id=tenant_id, status=status, limit=limit)
        response_items = [_to_review_queue_item_response(payload) for payload in items]
        return ReviewQueueListResponse(items=response_items, total=len(response_items))

    def _resolve_review_queue_item(
        review_id: str,
        payload: ReviewQueueResolveRequest,
    ) -> ReviewQueueItemResponse:
        try:
            item = review_queue.resolve(review_id=review_id, decision=payload.decision, note=payload.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="review item not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _to_review_queue_item_response(item)

    def _load_optional_json_file(file_path: str) -> Any:
        path_text = file_path.strip()
        if not path_text:
            return None

        path = Path(path_text)
        if not path.exists():
            return None

        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        return json.loads(content)

    def _summarize_queue_state(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"available": False, "message": "queue snapshot unavailable"}

        jobs = payload.get("jobs", {}) if isinstance(payload.get("jobs", {}), dict) else {}
        ready = payload.get("ready", []) if isinstance(payload.get("ready", []), list) else []
        dead_letter = payload.get("dead_letter", []) if isinstance(payload.get("dead_letter", []), list) else []
        leases = payload.get("leases", {}) if isinstance(payload.get("leases", {}), dict) else {}
        return {
            "available": True,
            "job_count": len(jobs),
            "ready_count": len(ready),
            "dead_letter_count": len(dead_letter),
            "lease_count": len(leases),
        }

    def _build_operator_console_payload() -> dict[str, Any]:
        artifact_payload = _load_optional_json_file(operator_artifacts_file_path)
        queue_payload = _load_optional_json_file(operator_queue_file_path)
        sessions = registry.list_sessions(page=1, page_size=50, tenant_id=None)
        traces = {
            "api": api_tracer.trace_snapshot(),
            "orchestrator": orchestrator_tracer.trace_snapshot(),
        }
        return {
            "sessions": sessions,
            "traces": traces,
            "artifacts": artifact_payload if artifact_payload is not None else {"available": False},
            "queue": _summarize_queue_state(queue_payload),
        }

    def _render_operator_console(payload: dict[str, Any]) -> str:
        sessions = payload["sessions"]
        traces = payload["traces"]
        artifacts = payload["artifacts"]
        queue = payload["queue"]

        session_rows = "".join(
            f"<tr><td>{item['session_id']}</td><td>{item['goal']}</td><td>{item['status']}</td><td>{item['tenant_id']}</td></tr>"
            for item in sessions.get("items", [])
        ) or "<tr><td colspan='4'>No sessions</td></tr>"

        traces_json = json.dumps(traces, indent=2)
        artifacts_json = json.dumps(artifacts, indent=2)
        queue_json = json.dumps(queue, indent=2)

        return f"""<!doctype html>
<html lang='en'>
<head>
    <meta charset='utf-8' />
    <title>Project Mimic Operator Console</title>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 24px; background: #0b1020; color: #e8edf7; }}
        h1, h2 {{ color: #f5f7ff; }}
        section {{ background: #121a31; border: 1px solid #24314f; border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ text-align: left; border-bottom: 1px solid #24314f; padding: 8px; vertical-align: top; }}
        pre {{ overflow: auto; background: #09101f; padding: 12px; border-radius: 8px; }}
        .muted {{ color: #a9b4cc; }}
    </style>
</head>
<body>
    <h1>Project Mimic Operator Console</h1>
    <p class='muted'>Sessions, traces, artifacts, and queue state snapshot</p>
    <section>
        <h2>Sessions</h2>
        <table>
            <thead><tr><th>Session</th><th>Goal</th><th>Status</th><th>Tenant</th></tr></thead>
            <tbody>{session_rows}</tbody>
        </table>
    </section>
    <section>
        <h2>Traces</h2>
        <pre>{traces_json}</pre>
    </section>
    <section>
        <h2>Artifacts</h2>
        <pre>{artifacts_json}</pre>
    </section>
    <section>
        <h2>Queue State</h2>
        <pre>{queue_json}</pre>
    </section>
</body>
</html>"""

    def _list_audit_events(
        *,
        action: str | None,
        tenant_id: str | None,
        limit: int,
    ) -> AuditLogListResponse:
        filtered = audit_events
        if action:
            filtered = [item for item in filtered if item["action"] == action]
        if tenant_id:
            filtered = [item for item in filtered if item["tenant_id"] == tenant_id]

        selected = list(reversed(filtered))[:limit]
        items = [AuditLogEntry(**item) for item in selected]
        return AuditLogListResponse(items=items, total=len(filtered))

    def _export_audit_events() -> AuditExportResponse:
        if audit_sink is None:
            raise HTTPException(status_code=400, detail="audit export destination is not configured")

        try:
            export_result = audit_sink.export(list(audit_events))
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"audit export failed: {exc}") from exc

        destination = str(export_result.get("destination", "unknown"))
        exported = int(export_result.get("exported", 0))
        metadata = {k: v for k, v in export_result.items() if k not in {"destination", "exported"}}
        return AuditExportResponse(exported=exported, destination=destination, metadata=metadata)

    def _reject_limit(
        request: Request,
        request_id: str,
        *,
        code: APIErrorCode,
        message: str,
        retry_after: int | None = None,
    ) -> JSONResponse:
        response = _error_response(
            request,
            status_code=429,
            code=code,
            message=message,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = request_id
        if retry_after is not None:
            response.headers["Retry-After"] = str(retry_after)
        return response

    def _reject_request_too_large(request: Request, request_id: str) -> JSONResponse:
        response = _error_response(
            request,
            status_code=413,
            code=APIErrorCode.REQUEST_TOO_LARGE,
            message="request body exceeds maximum allowed size",
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = request_id
        return response

    def _reject_request_timeout(request: Request, request_id: str) -> JSONResponse:
        response = _error_response(
            request,
            status_code=504,
            code=APIErrorCode.REQUEST_TIMEOUT,
            message="request exceeded timeout budget",
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = request_id
        return response

    def _enforce_tenant_limits(request: Request, request_id: str, tenant_id: str) -> JSONResponse | None:
        epoch_seconds = int(time.time())

        if rate_limit_per_minute > 0:
            minute_bucket = epoch_seconds // 60
            stale_keys = [key for key in tenant_minute_counters if key[1] < minute_bucket - 1]
            for key in stale_keys:
                tenant_minute_counters.pop(key, None)

            minute_key = (tenant_id, minute_bucket)
            tenant_minute_counters[minute_key] = tenant_minute_counters.get(minute_key, 0) + 1
            if tenant_minute_counters[minute_key] > rate_limit_per_minute:
                return _reject_limit(
                    request,
                    request_id,
                    code=APIErrorCode.RATE_LIMITED,
                    message="tenant rate limit exceeded",
                    retry_after=60,
                )

        if daily_quota > 0:
            day_bucket = epoch_seconds // 86400
            stale_days = [key for key in tenant_daily_counters if key[1] < day_bucket]
            for key in stale_days:
                tenant_daily_counters.pop(key, None)

            day_key = (tenant_id, day_bucket)
            tenant_daily_counters[day_key] = tenant_daily_counters.get(day_key, 0) + 1
            if tenant_daily_counters[day_key] > daily_quota:
                return _reject_limit(
                    request,
                    request_id,
                    code=APIErrorCode.QUOTA_EXCEEDED,
                    message="tenant daily quota exceeded",
                )

        return None

    def _error_response(
        request: Request,
        *,
        status_code: int,
        code: APIErrorCode | str,
        message: str,
        details: list[dict[str, Any]] | None = None,
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "request_id", None)
        safe_message = redact_sensitive_text(message)
        payload = APIErrorResponse(
            error=APIError(
                code=code.value if isinstance(code, APIErrorCode) else str(code),
                message=safe_message,
                correlation_id=correlation_id,
                details=redact_sensitive_structure(details or []),
            )
        )
        return JSONResponse(status_code=status_code, content=payload.model_dump())

    def _resolve_http_code(exc: HTTPException) -> APIErrorCode:
        detail = str(exc.detail).lower()
        if exc.status_code == 404 and "session" in detail:
            return APIErrorCode.SESSION_NOT_FOUND
        if exc.status_code == 410:
            return APIErrorCode.SESSION_EXPIRED
        if exc.status_code == 409:
            return APIErrorCode.SESSION_CONFLICT
        if exc.status_code == 403:
            return APIErrorCode.FORBIDDEN
        if exc.status_code == 422:
            return APIErrorCode.VALIDATION_ERROR
        return APIErrorCode.INTERNAL_ERROR

    def _create_session(payload: CreateSessionRequest, tenant_id: str) -> SessionCreatedResponse:
        session_id, observation = registry.create(
            goal=payload.goal,
            max_steps=payload.max_steps,
            tenant_id=tenant_id,
        )
        return SessionCreatedResponse(session_id=session_id, observation=observation)

    def _reset_session(session_id: str, payload: ResetSessionRequest, tenant_id: str) -> Observation:
        try:
            return registry.reset(session_id=session_id, goal=payload.goal, tenant_id=tenant_id)
        except SessionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except InvalidSessionTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SessionAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    def _step_session(session_id: str, action: UIAction, tenant_id: str) -> StepResponse:
        try:
            env = registry.get(session_id, tenant_id=tenant_id)
        except SessionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except SessionAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

        try:
            observation, reward, done, info = env.step(action)
            if done:
                registry.mark_completed(session_id, tenant_id=tenant_id)
            else:
                registry.save_checkpoint(session_id)
        except RuntimeError as exc:
            registry.mark_failed(session_id, tenant_id=tenant_id)
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        return StepResponse(observation=observation, reward=reward, done=done, info=info)

    def _state_session(session_id: str, tenant_id: str) -> dict[str, Any]:
        try:
            env = registry.get(session_id, tenant_id=tenant_id)
        except SessionExpiredError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except SessionAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

        return env.state()

    def _list_sessions(
        status: str | None,
        goal_contains: str | None,
        created_after: float | None,
        created_before: float | None,
        sort_by: str,
        sort_order: str,
        page: int,
        page_size: int,
        tenant_id: str,
    ) -> SessionListResponse:
        filter_status = SessionStatus(status) if status else None
        result = registry.list_sessions(
            status=filter_status,
            goal_contains=goal_contains,
            created_after=created_after,
            created_before=created_before,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            tenant_id=tenant_id,
        )
        return SessionListResponse(**result)

    def _restore_session(session_id: str, tenant_id: str) -> dict[str, Any]:
        try:
            return registry.restore(session_id, tenant_id=tenant_id)
        except SessionAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="checkpoint not found") from exc

    def _rollback_session(session_id: str, tenant_id: str) -> dict[str, Any]:
        try:
            return registry.rollback_to_checkpoint(session_id, tenant_id=tenant_id)
        except SessionAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _resume_session(session_id: str, tenant_id: str) -> dict[str, Any]:
        try:
            return registry.resume_from_checkpoint(session_id, tenant_id=tenant_id)
        except SessionAccessDeniedError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _new_api_key_secret() -> str:
        return f"pmk_{uuid4().hex}{uuid4().hex[:8]}"

    def _to_key_metadata(record: dict[str, Any]) -> APIKeyMetadata:
        return APIKeyMetadata(
            key_id=str(record["key_id"]),
            role=str(record["role"]),
            tenant_id=str(record["tenant_id"]),
            scopes=[str(scope) for scope in list(record.get("scopes", []))],
            active=bool(record.get("active", False)),
            created_at=float(record["created_at"]),
            last_rotated_at=(
                float(record["last_rotated_at"]) if record.get("last_rotated_at") is not None else None
            ),
        )

    def _create_api_key(payload: APIKeyCreateRequest) -> APIKeyCreateResponse:
        api_key = _new_api_key_secret()
        record = _register_api_key(
            secret=api_key,
            role=payload.role,
            tenant_id=payload.tenant_id,
            scopes=payload.scopes,
        )
        return APIKeyCreateResponse(
            key_id=str(record["key_id"]),
            api_key=api_key,
            role=str(record["role"]),
            tenant_id=str(record["tenant_id"]),
            scopes=[str(scope) for scope in list(record.get("scopes", []))],
        )

    def _list_api_keys() -> APIKeyListResponse:
        items = [_to_key_metadata(record) for record in api_key_records_by_id.values()]
        items.sort(key=lambda item: item.created_at)
        return APIKeyListResponse(items=items)

    def _rotate_api_key(key_id: str) -> APIKeyRotateResponse:
        record = api_key_records_by_id.get(key_id)
        if record is None:
            raise HTTPException(status_code=404, detail="api key not found")

        current_secrets = [secret for secret, candidate in key_id_by_secret.items() if candidate == key_id]
        for secret in current_secrets:
            key_id_by_secret.pop(secret, None)

        new_secret = _new_api_key_secret()
        key_id_by_secret[new_secret] = key_id
        rotated_at = time.time()
        record["last_rotated_at"] = rotated_at
        record["active"] = True
        return APIKeyRotateResponse(key_id=key_id, api_key=new_secret, rotated_at=rotated_at)

    def _revoke_api_key(key_id: str) -> APIKeyRevokeResponse:
        record = api_key_records_by_id.get(key_id)
        if record is None:
            raise HTTPException(status_code=404, detail="api key not found")

        record["active"] = False
        current_secrets = [secret for secret, candidate in key_id_by_secret.items() if candidate == key_id]
        for secret in current_secrets:
            key_id_by_secret.pop(secret, None)
        return APIKeyRevokeResponse(key_id=key_id, revoked=True)

    def _decide_click(payload: DecideRequest) -> DecideResponse:
        entities = [
            UIEntity(
                entity_id=item.entity_id,
                label=item.label,
                role=item.role,
                text=item.text,
                confidence=item.confidence,
                bbox=BBox(
                    x=item.bbox.x,
                    y=item.bbox.y,
                    width=item.bbox.width,
                    height=item.bbox.height,
                ),
            )
            for item in payload.entities
        ]

        dom_nodes = [
            DOMNode(
                dom_node_id=item.dom_node_id,
                role=item.role,
                text=item.text,
                visible=item.visible,
                enabled=item.enabled,
                z_index=item.z_index,
                bbox=BBox(
                    x=item.bbox.x,
                    y=item.bbox.y,
                    width=item.bbox.width,
                    height=item.bbox.height,
                ),
            )
            for item in payload.dom_nodes
        ]

        decision = engine.decide_coordinate_click(entities=entities, dom_nodes=dom_nodes)
        return DecideResponse(
            status=decision.status,
            state=decision.state.value,
            dom_node_id=decision.dom_node_id,
            x=decision.x,
            y=decision.y,
            score=decision.score,
        )

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id

        if max_request_body_bytes > 0:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > max_request_body_bytes:
                        return _reject_request_too_large(request, request_id)
                except ValueError:
                    pass

            body = await request.body()
            if len(body) > max_request_body_bytes:
                return _reject_request_too_large(request, request_id)

        if key_id_by_secret and not _is_auth_exempt_path(request.url.path):
            provided_key = request.headers.get("x-api-key", "")
            key_record = _lookup_active_key(provided_key)
            if key_record is None:
                unauthorized_response = _error_response(
                    request,
                    status_code=401,
                    code=APIErrorCode.UNAUTHORIZED,
                    message="missing or invalid api key",
                )
                unauthorized_response.headers["WWW-Authenticate"] = "ApiKey"
                unauthorized_response.headers["X-Request-ID"] = request_id
                unauthorized_response.headers["X-Correlation-ID"] = request_id
                return unauthorized_response

            caller_role = str(key_record["role"])
            required_role = _required_role_for_request(request.method, request.url.path)
            if role_rank[caller_role] < role_rank[required_role]:
                forbidden_response = _error_response(
                    request,
                    status_code=403,
                    code=APIErrorCode.FORBIDDEN,
                    message="role does not permit this operation",
                )
                forbidden_response.headers["X-Request-ID"] = request_id
                forbidden_response.headers["X-Correlation-ID"] = request_id
                return forbidden_response

            mapped_tenant = str(key_record["tenant_id"])
            header_tenant = request.headers.get("x-tenant-id", "").strip()
            if mapped_tenant and header_tenant and mapped_tenant != header_tenant:
                tenant_conflict = _error_response(
                    request,
                    status_code=403,
                    code=APIErrorCode.FORBIDDEN,
                    message="tenant header does not match key scope",
                )
                tenant_conflict.headers["X-Request-ID"] = request_id
                tenant_conflict.headers["X-Correlation-ID"] = request_id
                return tenant_conflict

            resolved_tenant = header_tenant or mapped_tenant or default_tenant
            if tenant_enforcement and not resolved_tenant:
                tenant_missing = _error_response(
                    request,
                    status_code=403,
                    code=APIErrorCode.FORBIDDEN,
                    message="tenant scope is required",
                )
                tenant_missing.headers["X-Request-ID"] = request_id
                tenant_missing.headers["X-Correlation-ID"] = request_id
                return tenant_missing

            request.state.api_key_id = str(key_record["key_id"])
            request.state.api_scopes = list(key_record.get("scopes", []))
            request.state.tenant_id = resolved_tenant
        else:
            request.state.tenant_id = request.headers.get("x-tenant-id", "").strip() or default_tenant

        if not _is_auth_exempt_path(request.url.path):
            throttled = _enforce_tenant_limits(request, request_id, _tenant_id(request))
            if throttled is not None:
                return throttled

        start = time.perf_counter()
        with api_tracer.start_span(
            "api.request",
            trace_id=request_id,
            attributes={"path": request.url.path, "method": request.method},
        ):
            try:
                if request_timeout_seconds > 0:
                    response = await asyncio.wait_for(call_next(request), timeout=request_timeout_seconds)
                else:
                    response = await call_next(request)
            except asyncio.TimeoutError:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                metrics.record(request.url.path, 504, elapsed_ms)
                timeout_response = _reject_request_timeout(request, request_id)
                timeout_response.headers["X-Request-ID"] = request_id
                timeout_response.headers["X-Correlation-ID"] = request_id
                return timeout_response
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metrics.record(request.url.path, response.status_code, elapsed_ms)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = request_id
        return response

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(request: Request, exc: RequestValidationError):
        return _error_response(
            request,
            status_code=422,
            code=APIErrorCode.REQUEST_VALIDATION_ERROR,
            message="request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        envelope = map_exception_to_error(exc)
        return _error_response(
            request,
            status_code=422,
            code=envelope.code.value,
            message=envelope.message,
            details=envelope.details,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return _error_response(
            request,
            status_code=exc.status_code,
            code=_resolve_http_code(exc),
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def uncaught_exception_handler(request: Request, exc: Exception):
        return _error_response(
            request,
            status_code=500,
            code=APIErrorCode.INTERNAL_ERROR,
            message=str(exc),
        )

    @app.on_event("startup")
    def startup_scavenger() -> None:
        def _loop() -> None:
            while not scavenger_stop.wait(scavenger_interval_seconds):
                registry.scavenge_expired()

        nonlocal scavenger_thread
        scavenger_thread = Thread(target=_loop, daemon=True, name="session-scavenger")
        scavenger_thread.start()

    @app.on_event("shutdown")
    def shutdown_scavenger() -> None:
        scavenger_stop.set()
        if scavenger_thread and scavenger_thread.is_alive():
            scavenger_thread.join(timeout=1.0)

    @app.get(DEPRECATION_DOC_PATH, response_model=DeprecationPolicyResponse)
    def deprecation_policy() -> DeprecationPolicyResponse:
        return DeprecationPolicyResponse(
            replacement_prefix=API_V1_PREFIX,
            deprecated_prefix=LEGACY_PREFIX,
            sunset=LEGACY_SUNSET_DATE,
            policy="Unversioned endpoints are supported for compatibility only and include deprecation headers.",
        )

    @app.post(f"{API_V1_PREFIX}/sessions", response_model=SessionCreatedResponse)
    def create_session_v1(payload: CreateSessionRequest, request: Request) -> SessionCreatedResponse:
        response = _create_session(payload, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.create",
            resource_type="session",
            resource_id=response.session_id,
            details={"goal": payload.goal},
        )
        metrics.record_feature_result(
            "session.create",
            success=True,
            trace_id=getattr(request.state, "request_id", None),
            goal=payload.goal,
            action_type="create",
        )
        _emit_lifecycle_event(
            request,
            event_type="session.create",
            session_id=response.session_id,
            details={"goal": payload.goal},
        )
        return response

    @app.post("/sessions", response_model=SessionCreatedResponse, deprecated=True)
    def create_session_legacy(
        payload: CreateSessionRequest,
        response: Response,
        request: Request,
    ) -> SessionCreatedResponse:
        _set_deprecation_headers(response)
        created = _create_session(payload, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.create",
            resource_type="session",
            resource_id=created.session_id,
            details={"goal": payload.goal},
        )
        metrics.record_feature_result(
            "session.create",
            success=True,
            trace_id=getattr(request.state, "request_id", None),
            goal=payload.goal,
            action_type="create",
        )
        _emit_lifecycle_event(
            request,
            event_type="session.create",
            session_id=created.session_id,
            details={"goal": payload.goal},
        )
        return created

    @app.post(f"{API_V1_PREFIX}/sessions/{{session_id}}/reset", response_model=Observation)
    def reset_session_v1(session_id: str, payload: ResetSessionRequest, request: Request) -> Observation:
        observation = _reset_session(session_id, payload, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.reset",
            resource_type="session",
            resource_id=session_id,
            details={"goal": payload.goal},
        )
        _emit_lifecycle_event(
            request,
            event_type="session.reset",
            session_id=session_id,
            details={"goal": payload.goal},
        )
        return observation

    @app.post("/sessions/{session_id}/reset", response_model=Observation, deprecated=True)
    def reset_session_legacy(
        session_id: str,
        payload: ResetSessionRequest,
        response: Response,
        request: Request,
    ) -> Observation:
        _set_deprecation_headers(response)
        observation = _reset_session(session_id, payload, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.reset",
            resource_type="session",
            resource_id=session_id,
            details={"goal": payload.goal},
        )
        _emit_lifecycle_event(
            request,
            event_type="session.reset",
            session_id=session_id,
            details={"goal": payload.goal},
        )
        return observation

    @app.post(f"{API_V1_PREFIX}/sessions/{{session_id}}/step", response_model=StepResponse)
    def step_session_v1(session_id: str, action: UIAction, request: Request) -> StepResponse:
        response = _step_session(session_id, action, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.step",
            resource_type="session",
            resource_id=session_id,
            details={"action_type": action.action_type.value},
        )
        goal = response.observation.goal
        metrics.record_feature_result(
            "session.step",
            success=True,
            trace_id=getattr(request.state, "request_id", None),
            goal=goal,
            action_type=action.action_type.value,
        )
        _emit_lifecycle_event(
            request,
            event_type="session.step",
            session_id=session_id,
            details={"action_type": action.action_type.value},
        )
        return response

    @app.post("/sessions/{session_id}/step", response_model=StepResponse, deprecated=True)
    def step_session_legacy(
        session_id: str,
        action: UIAction,
        response: Response,
        request: Request,
    ) -> StepResponse:
        _set_deprecation_headers(response)
        step_response = _step_session(session_id, action, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.step",
            resource_type="session",
            resource_id=session_id,
            details={"action_type": action.action_type.value},
        )
        metrics.record_feature_result(
            "session.step",
            success=True,
            trace_id=getattr(request.state, "request_id", None),
            goal=step_response.observation.goal,
            action_type=action.action_type.value,
        )
        _emit_lifecycle_event(
            request,
            event_type="session.step",
            session_id=session_id,
            details={"action_type": action.action_type.value},
        )
        return step_response

    @app.get(f"{API_V1_PREFIX}/sessions/{{session_id}}/state")
    def state_session_v1(session_id: str, request: Request) -> dict[str, Any]:
        return _state_session(session_id, tenant_id=_tenant_id(request))

    @app.get("/sessions/{session_id}/state", deprecated=True)
    def state_session_legacy(session_id: str, response: Response, request: Request) -> dict[str, Any]:
        _set_deprecation_headers(response)
        return _state_session(session_id, tenant_id=_tenant_id(request))

    @app.get(f"{API_V1_PREFIX}/sessions", response_model=SessionListResponse)
    def list_sessions_v1(
        request: Request,
        status: str | None = Query(default=None),
        goal_contains: str | None = Query(default=None, min_length=1),
        created_after: float | None = Query(default=None, ge=0),
        created_before: float | None = Query(default=None, ge=0),
        sort_by: str = Query(default="created_at"),
        sort_order: str = Query(default="desc"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> SessionListResponse:
        return _list_sessions(
            status=status,
            goal_contains=goal_contains,
            created_after=created_after,
            created_before=created_before,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            tenant_id=_tenant_id(request),
        )

    @app.get("/sessions", response_model=SessionListResponse, deprecated=True)
    def list_sessions_legacy(
        response: Response,
        request: Request,
        status: str | None = Query(default=None),
        goal_contains: str | None = Query(default=None, min_length=1),
        created_after: float | None = Query(default=None, ge=0),
        created_before: float | None = Query(default=None, ge=0),
        sort_by: str = Query(default="created_at"),
        sort_order: str = Query(default="desc"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> SessionListResponse:
        _set_deprecation_headers(response)
        return _list_sessions(
            status=status,
            goal_contains=goal_contains,
            created_after=created_after,
            created_before=created_before,
            sort_by=sort_by,
            sort_order=sort_order,
            page=page,
            page_size=page_size,
            tenant_id=_tenant_id(request),
        )

    @app.get(f"{API_V1_PREFIX}/sessions/{{session_id}}/restore")
    def restore_session_v1(session_id: str, request: Request) -> dict[str, Any]:
        return _restore_session(session_id, tenant_id=_tenant_id(request))

    @app.get("/sessions/{session_id}/restore", deprecated=True)
    def restore_session_legacy(session_id: str, response: Response, request: Request) -> dict[str, Any]:
        _set_deprecation_headers(response)
        return _restore_session(session_id, tenant_id=_tenant_id(request))

    @app.post(f"{API_V1_PREFIX}/sessions/{{session_id}}/rollback")
    def rollback_session_v1(session_id: str, request: Request) -> dict[str, Any]:
        payload = _rollback_session(session_id, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.rollback",
            resource_type="session",
            resource_id=session_id,
        )
        _emit_lifecycle_event(request, event_type="session.rollback", session_id=session_id)
        return payload

    @app.post("/sessions/{session_id}/rollback", deprecated=True)
    def rollback_session_legacy(session_id: str, response: Response, request: Request) -> dict[str, Any]:
        _set_deprecation_headers(response)
        payload = _rollback_session(session_id, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.rollback",
            resource_type="session",
            resource_id=session_id,
        )
        _emit_lifecycle_event(request, event_type="session.rollback", session_id=session_id)
        return payload

    @app.post(f"{API_V1_PREFIX}/sessions/{{session_id}}/resume")
    def resume_session_v1(session_id: str, request: Request) -> dict[str, Any]:
        payload = _resume_session(session_id, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.resume",
            resource_type="session",
            resource_id=session_id,
        )
        _emit_lifecycle_event(request, event_type="session.resume", session_id=session_id)
        return payload

    @app.post("/sessions/{session_id}/resume", deprecated=True)
    def resume_session_legacy(session_id: str, response: Response, request: Request) -> dict[str, Any]:
        _set_deprecation_headers(response)
        payload = _resume_session(session_id, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="session.resume",
            resource_type="session",
            resource_id=session_id,
        )
        _emit_lifecycle_event(request, event_type="session.resume", session_id=session_id)
        return payload

    @app.post(f"{API_V1_PREFIX}/jobs", response_model=AsyncJobSubmitResponse)
    def submit_async_job_v1(payload: AsyncJobSubmitRequest, request: Request) -> AsyncJobSubmitResponse:
        submitted = _submit_async_job(payload)
        _append_audit_event(
            request,
            action="async_job.submit",
            resource_type="async_job",
            resource_id=submitted.job.job_id,
            details={"job_type": payload.job_type},
        )
        _publish_realtime_event(
            event_type="async_job.submit",
            tenant_id=_tenant_id(request),
            payload={
                "job_id": submitted.job.job_id,
                "job_type": payload.job_type,
                "status": submitted.job.status,
            },
        )
        return submitted

    @app.post("/jobs", response_model=AsyncJobSubmitResponse, deprecated=True)
    def submit_async_job_legacy(
        payload: AsyncJobSubmitRequest,
        response: Response,
        request: Request,
    ) -> AsyncJobSubmitResponse:
        _set_deprecation_headers(response)
        submitted = _submit_async_job(payload)
        _append_audit_event(
            request,
            action="async_job.submit",
            resource_type="async_job",
            resource_id=submitted.job.job_id,
            details={"job_type": payload.job_type},
        )
        _publish_realtime_event(
            event_type="async_job.submit",
            tenant_id=_tenant_id(request),
            payload={
                "job_id": submitted.job.job_id,
                "job_type": payload.job_type,
                "status": submitted.job.status,
            },
        )
        return submitted

    @app.get(f"{API_V1_PREFIX}/jobs/{{job_id}}", response_model=AsyncJobResponse)
    def get_async_job_v1(job_id: str) -> AsyncJobResponse:
        return _get_async_job(job_id)

    @app.get("/jobs/{job_id}", response_model=AsyncJobResponse, deprecated=True)
    def get_async_job_legacy(job_id: str, response: Response) -> AsyncJobResponse:
        _set_deprecation_headers(response)
        return _get_async_job(job_id)

    @app.post(f"{API_V1_PREFIX}/jobs/{{job_id}}/cancel", response_model=AsyncJobCancelResponse)
    def cancel_async_job_v1(job_id: str, request: Request) -> AsyncJobCancelResponse:
        canceled = _cancel_async_job(job_id)
        _append_audit_event(
            request,
            action="async_job.cancel",
            resource_type="async_job",
            resource_id=job_id,
        )
        _publish_realtime_event(
            event_type="async_job.cancel",
            tenant_id=_tenant_id(request),
            payload={"job_id": job_id, "status": canceled.job.status},
        )
        return canceled

    @app.post("/jobs/{job_id}/cancel", response_model=AsyncJobCancelResponse, deprecated=True)
    def cancel_async_job_legacy(job_id: str, response: Response, request: Request) -> AsyncJobCancelResponse:
        _set_deprecation_headers(response)
        canceled = _cancel_async_job(job_id)
        _append_audit_event(
            request,
            action="async_job.cancel",
            resource_type="async_job",
            resource_id=job_id,
        )
        _publish_realtime_event(
            event_type="async_job.cancel",
            tenant_id=_tenant_id(request),
            payload={"job_id": job_id, "status": canceled.job.status},
        )
        return canceled

    @app.get(f"{API_V1_PREFIX}/audit/logs", response_model=AuditLogListResponse)
    def list_audit_logs_v1(
        action: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> AuditLogListResponse:
        return _list_audit_events(action=action, tenant_id=tenant_id, limit=limit)

    @app.get("/audit/logs", response_model=AuditLogListResponse, deprecated=True)
    def list_audit_logs_legacy(
        response: Response,
        action: str | None = Query(default=None),
        tenant_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> AuditLogListResponse:
        _set_deprecation_headers(response)
        return _list_audit_events(action=action, tenant_id=tenant_id, limit=limit)

    @app.post(f"{API_V1_PREFIX}/audit/export", response_model=AuditExportResponse)
    def export_audit_logs_v1() -> AuditExportResponse:
        return _export_audit_events()

    @app.post("/audit/export", response_model=AuditExportResponse, deprecated=True)
    def export_audit_logs_legacy(response: Response) -> AuditExportResponse:
        _set_deprecation_headers(response)
        return _export_audit_events()

    @app.post(f"{API_V1_PREFIX}/events/subscriptions", response_model=WebhookSubscriptionResponse)
    def create_event_subscription_v1(
        payload: WebhookSubscriptionCreateRequest,
        request: Request,
    ) -> WebhookSubscriptionResponse:
        created = webhook_publisher.create_subscription(
            name=payload.name,
            callback_url=payload.callback_url,
            events=payload.events,
            tenant_id=_tenant_id(request),
            secret=payload.secret,
        )
        response_model = _to_webhook_subscription_response(created)
        _append_audit_event(
            request,
            action="event.subscription.create",
            resource_type="webhook_subscription",
            resource_id=response_model.subscription_id,
            details={"name": response_model.name, "events": response_model.events},
        )
        return response_model

    @app.post("/events/subscriptions", response_model=WebhookSubscriptionResponse, deprecated=True)
    def create_event_subscription_legacy(
        payload: WebhookSubscriptionCreateRequest,
        response: Response,
        request: Request,
    ) -> WebhookSubscriptionResponse:
        _set_deprecation_headers(response)
        created = webhook_publisher.create_subscription(
            name=payload.name,
            callback_url=payload.callback_url,
            events=payload.events,
            tenant_id=_tenant_id(request),
            secret=payload.secret,
        )
        response_model = _to_webhook_subscription_response(created)
        _append_audit_event(
            request,
            action="event.subscription.create",
            resource_type="webhook_subscription",
            resource_id=response_model.subscription_id,
            details={"name": response_model.name, "events": response_model.events},
        )
        return response_model

    @app.get(f"{API_V1_PREFIX}/events/subscriptions", response_model=WebhookSubscriptionListResponse)
    def list_event_subscriptions_v1(request: Request) -> WebhookSubscriptionListResponse:
        items = [
            _to_webhook_subscription_response(payload)
            for payload in webhook_publisher.list_subscriptions(tenant_id=_tenant_id(request))
        ]
        return WebhookSubscriptionListResponse(items=items, total=len(items))

    @app.get("/events/subscriptions", response_model=WebhookSubscriptionListResponse, deprecated=True)
    def list_event_subscriptions_legacy(response: Response, request: Request) -> WebhookSubscriptionListResponse:
        _set_deprecation_headers(response)
        items = [
            _to_webhook_subscription_response(payload)
            for payload in webhook_publisher.list_subscriptions(tenant_id=_tenant_id(request))
        ]
        return WebhookSubscriptionListResponse(items=items, total=len(items))

    @app.get(f"{API_V1_PREFIX}/events/stream")
    def stream_events_v1(
        request: Request,
        after_id: int = Query(default=0, ge=0),
        max_events: int = Query(default=100, ge=1, le=500),
        wait_seconds: float = Query(default=5.0, ge=0.0, le=30.0),
        event_type: str | None = Query(default=None, min_length=1),
    ) -> StreamingResponse:
        return _build_event_stream_response(
            tenant_id=_tenant_id(request),
            after_id=after_id,
            max_events=max_events,
            wait_seconds=wait_seconds,
            event_type=event_type,
        )

    @app.get("/events/stream", deprecated=True)
    def stream_events_legacy(
        request: Request,
        after_id: int = Query(default=0, ge=0),
        max_events: int = Query(default=100, ge=1, le=500),
        wait_seconds: float = Query(default=5.0, ge=0.0, le=30.0),
        event_type: str | None = Query(default=None, min_length=1),
    ) -> StreamingResponse:
        response = _build_event_stream_response(
            tenant_id=_tenant_id(request),
            after_id=after_id,
            max_events=max_events,
            wait_seconds=wait_seconds,
            event_type=event_type,
        )
        _set_deprecation_headers(response)
        return response

    @app.post(f"{API_V1_PREFIX}/models/registry/register")
    def register_model_version_v1(
        payload: ModelRegisterRequest,
        request: Request,
    ) -> dict[str, Any]:
        registered = _register_model_version(payload)
        _append_audit_event(
            request,
            action="model.registry.register",
            resource_type="model_version",
            resource_id=f"{registered['model_id']}::{registered['version']}",
        )
        return registered

    @app.post("/models/registry/register", deprecated=True)
    def register_model_version_legacy(
        payload: ModelRegisterRequest,
        response: Response,
        request: Request,
    ) -> dict[str, Any]:
        _set_deprecation_headers(response)
        registered = _register_model_version(payload)
        _append_audit_event(
            request,
            action="model.registry.register",
            resource_type="model_version",
            resource_id=f"{registered['model_id']}::{registered['version']}",
        )
        return registered

    @app.get(f"{API_V1_PREFIX}/models/registry/versions", response_model=ModelVersionListResponse)
    def list_model_versions_v1(model_id: str | None = Query(default=None)) -> ModelVersionListResponse:
        return _list_model_versions(model_id=model_id)

    @app.get("/models/registry/versions", response_model=ModelVersionListResponse, deprecated=True)
    def list_model_versions_legacy(
        response: Response,
        model_id: str | None = Query(default=None),
    ) -> ModelVersionListResponse:
        _set_deprecation_headers(response)
        return _list_model_versions(model_id=model_id)

    @app.post(f"{API_V1_PREFIX}/models/registry/channels/{{channel}}/promote", response_model=ModelPromotionResponse)
    def promote_model_channel_v1(
        channel: str,
        payload: ModelPromotionRequest,
        request: Request,
    ) -> ModelPromotionResponse:
        promoted = _promote_model_channel(channel, payload)
        _append_audit_event(
            request,
            action="model.registry.promote",
            resource_type="model_channel",
            resource_id=channel,
            details=promoted.assignment,
        )
        return promoted

    @app.post("/models/registry/channels/{channel}/promote", response_model=ModelPromotionResponse, deprecated=True)
    def promote_model_channel_legacy(
        channel: str,
        payload: ModelPromotionRequest,
        response: Response,
        request: Request,
    ) -> ModelPromotionResponse:
        _set_deprecation_headers(response)
        promoted = _promote_model_channel(channel, payload)
        _append_audit_event(
            request,
            action="model.registry.promote",
            resource_type="model_channel",
            resource_id=channel,
            details=promoted.assignment,
        )
        return promoted

    @app.get(f"{API_V1_PREFIX}/models/registry/channels", response_model=ModelChannelListResponse)
    def list_model_channels_v1() -> ModelChannelListResponse:
        return ModelChannelListResponse(channels=model_registry.list_channels())

    @app.get("/models/registry/channels", response_model=ModelChannelListResponse, deprecated=True)
    def list_model_channels_legacy(response: Response) -> ModelChannelListResponse:
        _set_deprecation_headers(response)
        return ModelChannelListResponse(channels=model_registry.list_channels())

    @app.post(f"{API_V1_PREFIX}/drift/samples", response_model=DriftStatusResponse)
    def ingest_drift_sample_v1(payload: DriftSampleRequest, request: Request) -> DriftStatusResponse:
        status = _record_drift_sample(payload)
        _append_audit_event(
            request,
            action="drift.sample.ingest",
            resource_type="drift_metric",
            resource_id=f"{payload.stream_id}::{payload.metric_name}",
        )
        if status.alert_active:
            _publish_realtime_event(
                event_type="drift.alert",
                tenant_id=_tenant_id(request),
                payload={
                    "stream_id": status.stream_id,
                    "metric_name": status.metric_name,
                    "drift_score": status.drift_score,
                    "threshold": status.threshold,
                },
            )
        return status

    @app.post("/drift/samples", response_model=DriftStatusResponse, deprecated=True)
    def ingest_drift_sample_legacy(
        payload: DriftSampleRequest,
        response: Response,
        request: Request,
    ) -> DriftStatusResponse:
        _set_deprecation_headers(response)
        status = _record_drift_sample(payload)
        _append_audit_event(
            request,
            action="drift.sample.ingest",
            resource_type="drift_metric",
            resource_id=f"{payload.stream_id}::{payload.metric_name}",
        )
        if status.alert_active:
            _publish_realtime_event(
                event_type="drift.alert",
                tenant_id=_tenant_id(request),
                payload={
                    "stream_id": status.stream_id,
                    "metric_name": status.metric_name,
                    "drift_score": status.drift_score,
                    "threshold": status.threshold,
                },
            )
        return status

    @app.get(f"{API_V1_PREFIX}/drift/status", response_model=DriftStatusResponse)
    def drift_status_v1(
        stream_id: str = Query(..., min_length=1),
        metric_name: str = Query(..., min_length=1),
    ) -> DriftStatusResponse:
        return _drift_status(stream_id, metric_name)

    @app.get("/drift/status", response_model=DriftStatusResponse, deprecated=True)
    def drift_status_legacy(
        response: Response,
        stream_id: str = Query(..., min_length=1),
        metric_name: str = Query(..., min_length=1),
    ) -> DriftStatusResponse:
        _set_deprecation_headers(response)
        return _drift_status(stream_id, metric_name)

    @app.get(f"{API_V1_PREFIX}/drift/alerts", response_model=DriftAlertListResponse)
    def list_drift_alerts_v1() -> DriftAlertListResponse:
        return _list_drift_alerts()

    @app.get("/drift/alerts", response_model=DriftAlertListResponse, deprecated=True)
    def list_drift_alerts_legacy(response: Response) -> DriftAlertListResponse:
        _set_deprecation_headers(response)
        return _list_drift_alerts()

    @app.post(f"{API_V1_PREFIX}/reviews/queue", response_model=ReviewQueueItemResponse)
    def submit_review_queue_item_v1(
        payload: ReviewQueueSubmitRequest,
        request: Request,
    ) -> ReviewQueueItemResponse:
        item = _submit_review_queue_item(payload, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="review.queue.submit",
            resource_type="review_item",
            resource_id=item.review_id,
            details={"confidence": item.confidence},
        )
        _publish_realtime_event(
            event_type="review.queue.submitted",
            tenant_id=_tenant_id(request),
            payload={
                "review_id": item.review_id,
                "confidence": item.confidence,
                "status": item.status,
            },
        )
        return item

    @app.post("/reviews/queue", response_model=ReviewQueueItemResponse, deprecated=True)
    def submit_review_queue_item_legacy(
        payload: ReviewQueueSubmitRequest,
        response: Response,
        request: Request,
    ) -> ReviewQueueItemResponse:
        _set_deprecation_headers(response)
        item = _submit_review_queue_item(payload, tenant_id=_tenant_id(request))
        _append_audit_event(
            request,
            action="review.queue.submit",
            resource_type="review_item",
            resource_id=item.review_id,
            details={"confidence": item.confidence},
        )
        _publish_realtime_event(
            event_type="review.queue.submitted",
            tenant_id=_tenant_id(request),
            payload={
                "review_id": item.review_id,
                "confidence": item.confidence,
                "status": item.status,
            },
        )
        return item

    @app.get(f"{API_V1_PREFIX}/reviews/queue", response_model=ReviewQueueListResponse)
    def list_review_queue_items_v1(
        request: Request,
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> ReviewQueueListResponse:
        return _list_review_queue_items(tenant_id=_tenant_id(request), status=status, limit=limit)

    @app.get("/reviews/queue", response_model=ReviewQueueListResponse, deprecated=True)
    def list_review_queue_items_legacy(
        response: Response,
        request: Request,
        status: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> ReviewQueueListResponse:
        _set_deprecation_headers(response)
        return _list_review_queue_items(tenant_id=_tenant_id(request), status=status, limit=limit)

    @app.post(f"{API_V1_PREFIX}/reviews/queue/{{review_id}}/resolve", response_model=ReviewQueueItemResponse)
    def resolve_review_queue_item_v1(
        review_id: str,
        payload: ReviewQueueResolveRequest,
        request: Request,
    ) -> ReviewQueueItemResponse:
        item = _resolve_review_queue_item(review_id, payload)
        _append_audit_event(
            request,
            action="review.queue.resolve",
            resource_type="review_item",
            resource_id=item.review_id,
            details={"resolution": item.resolution},
        )
        _publish_realtime_event(
            event_type="review.queue.resolved",
            tenant_id=_tenant_id(request),
            payload={
                "review_id": item.review_id,
                "resolution": item.resolution,
                "status": item.status,
            },
        )
        return item

    @app.post("/reviews/queue/{review_id}/resolve", response_model=ReviewQueueItemResponse, deprecated=True)
    def resolve_review_queue_item_legacy(
        review_id: str,
        payload: ReviewQueueResolveRequest,
        response: Response,
        request: Request,
    ) -> ReviewQueueItemResponse:
        _set_deprecation_headers(response)
        item = _resolve_review_queue_item(review_id, payload)
        _append_audit_event(
            request,
            action="review.queue.resolve",
            resource_type="review_item",
            resource_id=item.review_id,
            details={"resolution": item.resolution},
        )
        _publish_realtime_event(
            event_type="review.queue.resolved",
            tenant_id=_tenant_id(request),
            payload={
                "review_id": item.review_id,
                "resolution": item.resolution,
                "status": item.status,
            },
        )
        return item

    @app.get(f"{API_V1_PREFIX}/auth/keys", response_model=APIKeyListResponse)
    def list_api_keys_v1() -> APIKeyListResponse:
        return _list_api_keys()

    @app.get("/auth/keys", response_model=APIKeyListResponse, deprecated=True)
    def list_api_keys_legacy(response: Response) -> APIKeyListResponse:
        _set_deprecation_headers(response)
        return _list_api_keys()

    @app.post(f"{API_V1_PREFIX}/auth/keys", response_model=APIKeyCreateResponse)
    def create_api_key_v1(payload: APIKeyCreateRequest, request: Request) -> APIKeyCreateResponse:
        created = _create_api_key(payload)
        _append_audit_event(
            request,
            action="auth.key.create",
            resource_type="api_key",
            resource_id=created.key_id,
            details={"role": created.role, "tenant_id": created.tenant_id},
        )
        return created

    @app.post("/auth/keys", response_model=APIKeyCreateResponse, deprecated=True)
    def create_api_key_legacy(
        payload: APIKeyCreateRequest,
        response: Response,
        request: Request,
    ) -> APIKeyCreateResponse:
        _set_deprecation_headers(response)
        created = _create_api_key(payload)
        _append_audit_event(
            request,
            action="auth.key.create",
            resource_type="api_key",
            resource_id=created.key_id,
            details={"role": created.role, "tenant_id": created.tenant_id},
        )
        return created

    @app.post(f"{API_V1_PREFIX}/auth/keys/{{key_id}}/rotate", response_model=APIKeyRotateResponse)
    def rotate_api_key_v1(key_id: str, request: Request) -> APIKeyRotateResponse:
        rotated = _rotate_api_key(key_id)
        _append_audit_event(
            request,
            action="auth.key.rotate",
            resource_type="api_key",
            resource_id=key_id,
        )
        return rotated

    @app.post("/auth/keys/{key_id}/rotate", response_model=APIKeyRotateResponse, deprecated=True)
    def rotate_api_key_legacy(key_id: str, response: Response, request: Request) -> APIKeyRotateResponse:
        _set_deprecation_headers(response)
        rotated = _rotate_api_key(key_id)
        _append_audit_event(
            request,
            action="auth.key.rotate",
            resource_type="api_key",
            resource_id=key_id,
        )
        return rotated

    @app.post(f"{API_V1_PREFIX}/auth/keys/{{key_id}}/revoke", response_model=APIKeyRevokeResponse)
    def revoke_api_key_v1(key_id: str, request: Request) -> APIKeyRevokeResponse:
        revoked = _revoke_api_key(key_id)
        _append_audit_event(
            request,
            action="auth.key.revoke",
            resource_type="api_key",
            resource_id=key_id,
        )
        return revoked

    @app.post("/auth/keys/{key_id}/revoke", response_model=APIKeyRevokeResponse, deprecated=True)
    def revoke_api_key_legacy(key_id: str, response: Response, request: Request) -> APIKeyRevokeResponse:
        _set_deprecation_headers(response)
        revoked = _revoke_api_key(key_id)
        _append_audit_event(
            request,
            action="auth.key.revoke",
            resource_type="api_key",
            resource_id=key_id,
        )
        return revoked

    @app.post(
        f"{API_V1_PREFIX}/decision/click",
        response_model=DecideResponse,
        openapi_extra={
            "responses": {
                "200": {
                    "description": "Best click candidate chosen from grounded entities",
                    "content": {
                        "application/json": {
                            "example": {
                                "status": "ok",
                                "state": "complete",
                                "dom_node_id": "search-btn",
                                "x": 162,
                                "y": 121,
                                "score": 0.93,
                            }
                        }
                    },
                }
            }
        },
    )
    def decide_click_v1(payload: DecideRequest, request: Request) -> DecideResponse:
        response = _decide_click(payload)
        metrics.record_feature_result(
            "orchestrator.decision",
            success=response.status == "ok",
            trace_id=getattr(request.state, "request_id", None),
            action_type="click",
        )
        return response

    @app.post("/decision/click", response_model=DecideResponse, deprecated=True)
    def decide_click_legacy(payload: DecideRequest, response: Response, request: Request) -> DecideResponse:
        _set_deprecation_headers(response)
        decide_response = _decide_click(payload)
        metrics.record_feature_result(
            "orchestrator.decision",
            success=decide_response.status == "ok",
            trace_id=getattr(request.state, "request_id", None),
            action_type="click",
        )
        return decide_response

    @app.get(f"{API_V1_PREFIX}/metrics")
    def get_metrics_v1() -> dict[str, Any]:
        snapshot = metrics.snapshot()
        snapshot["traces"] = {
            "api": api_tracer.trace_snapshot(),
            "orchestrator": orchestrator_tracer.trace_snapshot(),
        }
        return snapshot

    @app.get("/metrics", deprecated=True)
    def get_metrics_legacy(response: Response) -> dict[str, Any]:
        _set_deprecation_headers(response)
        snapshot = metrics.snapshot()
        snapshot["traces"] = {
            "api": api_tracer.trace_snapshot(),
            "orchestrator": orchestrator_tracer.trace_snapshot(),
        }
        return snapshot

    @app.get(f"{API_V1_PREFIX}/operator")
    def get_operator_console_v1() -> HTMLResponse:
        payload = _build_operator_console_payload()
        return HTMLResponse(content=_render_operator_console(payload))

    @app.get("/operator", deprecated=True)
    def get_operator_console_legacy(response: Response) -> HTMLResponse:
        _set_deprecation_headers(response)
        payload = _build_operator_console_payload()
        return HTMLResponse(content=_render_operator_console(payload))

    @app.get(f"{API_V1_PREFIX}/operator/snapshot")
    def get_operator_snapshot_v1() -> dict[str, Any]:
        return _build_operator_console_payload()

    @app.get("/operator/snapshot", deprecated=True)
    def get_operator_snapshot_legacy(response: Response) -> dict[str, Any]:
        _set_deprecation_headers(response)
        return _build_operator_console_payload()

    return app


app = create_app()
