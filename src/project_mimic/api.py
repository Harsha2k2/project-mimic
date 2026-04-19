"""FastAPI service for Project Mimic environment sessions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import html
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
from .billing import BillingPrimitives, InMemoryBillingStore, JsonFileBillingStore
from .cost_aware_scheduler import (
    CostAwareScheduler,
    InMemoryCostAwareSchedulerStore,
    JsonFileCostAwareSchedulerStore,
)
from .data_residency import (
    InMemoryDataResidencyStore,
    JsonFileDataResidencyStore,
    TenantDataResidencyPolicyService,
)
from .drift_detection import DriftMonitor
from .engine import ExecutionEngine
from .event_stream import EventStreamBroker
from .feature_flags import FeatureFlagService, InMemoryFeatureFlagStore, JsonFileFeatureFlagStore
from .governance_controls import (
    ConsentTargetGovernanceService,
    InMemoryGovernancePolicyStore,
    JsonFileGovernancePolicyStore,
)
from .multi_region_control_plane import (
    InMemoryMultiRegionControlPlaneStore,
    JsonFileMultiRegionControlPlaneStore,
    MultiRegionControlPlaneService,
)
from .model_registry import InMemoryModelRegistryStore, JsonFileModelRegistryStore, ModelRegistry
from .site_pack_registry import InMemorySitePackRegistryStore, JsonFileSitePackRegistryStore, SitePackRegistry
from .models import Observation, ProjectMimicModel, Reward, UIAction
from .observability import InMemoryMetrics, OpenTelemetryTracer
from .policy_explorer import InMemoryPolicyDecisionStore, JsonFilePolicyDecisionStore, PolicyDecisionExplorer
from .queue_runtime import ActionJob, InMemoryActionQueue, JsonFileQueueStore
from .review_queue import HumanReviewQueue, InMemoryReviewQueueStore, JsonFileReviewQueueStore
from .regional_failover import (
    InMemoryRegionalFailoverStore,
    JsonFileRegionalFailoverStore,
    RegionalFailoverOrchestrator,
)
from .security import redact_sensitive_structure, redact_sensitive_text
from .synthetic_monitoring import SyntheticMonitor
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
from .usage_metering import InMemoryUsageMeteringStore, JsonFileUsageMeteringStore, TenantUsageMetering
from .webhooks import (
    InMemoryWebhookSubscriptionStore,
    JsonFileWebhookSubscriptionStore,
    LifecycleEventWebhookPublisher,
)
from .vision.grounding import BBox, DOMNode, UIEntity
from .vision.triton_client import TritonConfig, TritonVisionClient


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


class SitePackRegisterRequest(APIPayloadModel):
    pack_id: str
    version: str
    strategy_class: str
    artifact_uri: str
    site_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SitePackVersionListResponse(APIPayloadModel):
    items: list[dict[str, Any]]
    total: int


class SitePackPromotionRequest(APIPayloadModel):
    pack_id: str
    version: str


class SitePackPromotionResponse(APIPayloadModel):
    assignment: dict[str, Any]


class SitePackChannelListResponse(APIPayloadModel):
    channels: dict[str, dict[str, Any] | None]


class SitePackRuntimeStrategyMapResponse(APIPayloadModel):
    mappings: dict[str, str]


class FeatureFlagUpsertRequest(APIPayloadModel):
    flag_key: str
    description: str = ""
    enabled: bool = True
    rollout_percentage: int = Field(default=100, ge=0, le=100)
    tenant_allowlist: list[str] = Field(default_factory=list)
    subject_allowlist: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)


class FeatureFlagResponse(APIPayloadModel):
    flag_key: str
    description: str
    enabled: bool
    rollout_percentage: int
    tenant_allowlist: list[str] = Field(default_factory=list)
    subject_allowlist: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class FeatureFlagListResponse(APIPayloadModel):
    items: list[FeatureFlagResponse]
    total: int


class FeatureFlagDeleteResponse(APIPayloadModel):
    flag_key: str
    deleted: bool


class FeatureFlagEvaluationRequest(APIPayloadModel):
    flag_key: str
    subject_key: str
    tenant_id: str | None = None


class FeatureFlagEvaluationResponse(APIPayloadModel):
    flag_key: str
    subject_key: str
    tenant_id: str
    enabled: bool
    reason: str
    bucket: int | None = None
    rollout_percentage: int
    matched_allowlist: bool
    evaluated_at: float


class UsageRecordResponse(APIPayloadModel):
    record_key: str
    tenant_id: str
    dimension: str
    day_bucket: int
    units: float
    created_at: float
    updated_at: float


class UsageRecordListResponse(APIPayloadModel):
    items: list[UsageRecordResponse]
    total: int


class UsageSummaryResponse(APIPayloadModel):
    tenant_id: str
    start_day: int | None = None
    end_day: int | None = None
    dimensions: dict[str, float] = Field(default_factory=dict)
    total_units: float


class BillingPlanUpsertRequest(APIPayloadModel):
    plan_id: str
    description: str = ""
    included_units: dict[str, float] = Field(default_factory=dict)
    hard_limits: bool = True
    overage_buffer_units: dict[str, float] = Field(default_factory=dict)


class BillingPlanResponse(APIPayloadModel):
    plan_id: str
    description: str
    included_units: dict[str, float] = Field(default_factory=dict)
    hard_limits: bool
    overage_buffer_units: dict[str, float] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class BillingPlanListResponse(APIPayloadModel):
    items: list[BillingPlanResponse]
    total: int


class BillingSubscriptionAssignRequest(APIPayloadModel):
    plan_id: str
    overage_protection: bool = True


class BillingSubscriptionResponse(APIPayloadModel):
    tenant_id: str
    plan_id: str
    overage_protection: bool
    started_at: float
    updated_at: float


class BillingOverageStatusResponse(APIPayloadModel):
    tenant_id: str
    plan_id: str | None = None
    overage_protection: bool
    usage_dimensions: dict[str, float] = Field(default_factory=dict)
    limits: dict[str, float] = Field(default_factory=dict)
    overage_buffer_units: dict[str, float] = Field(default_factory=dict)
    exceeded_dimensions: dict[str, float] = Field(default_factory=dict)
    blocked_dimensions: list[str] = Field(default_factory=list)
    blocked: bool
    within_limits: bool


class BillingMonthlyReportResponse(BillingOverageStatusResponse):
    month: str
    generated_at: float


class DataResidencyPolicyUpsertRequest(APIPayloadModel):
    allowed_regions: list[str] = Field(default_factory=list)
    default_region: str | None = None


class DataResidencyPolicyResponse(APIPayloadModel):
    tenant_id: str
    allowed_regions: list[str] = Field(default_factory=list)
    default_region: str
    created_at: float
    updated_at: float


class DataResidencyPolicyListResponse(APIPayloadModel):
    items: list[DataResidencyPolicyResponse]
    total: int


class DataResidencyValidationResponse(APIPayloadModel):
    tenant_id: str
    region: str
    allowed: bool
    reason: str
    allowed_regions: list[str] = Field(default_factory=list)
    default_region: str | None = None


class ControlPlaneRegionUpsertRequest(APIPayloadModel):
    endpoint: str
    traffic_weight: float = Field(default=1.0, gt=0.0)
    write_enabled: bool = True
    read_enabled: bool = True
    priority: int = Field(default=100, ge=0)


class ControlPlaneRegionResponse(APIPayloadModel):
    region_id: str
    endpoint: str
    traffic_weight: float
    write_enabled: bool
    read_enabled: bool
    priority: int
    healthy: bool
    health_reason: str | None = None
    last_heartbeat_at: float
    created_at: float
    updated_at: float


class ControlPlaneRegionListResponse(APIPayloadModel):
    items: list[ControlPlaneRegionResponse]
    total: int


class ControlPlaneRegionHealthRequest(APIPayloadModel):
    healthy: bool
    reason: str | None = None


class ControlPlaneRouteRequest(APIPayloadModel):
    tenant_id: str | None = None
    operation: str = "read"
    preferred_region: str | None = None


class ControlPlaneRouteResponse(APIPayloadModel):
    tenant_id: str
    operation: str
    selected_region: str
    endpoint: str
    reason: str
    routed_at: float


class ControlPlaneTopologyResponse(APIPayloadModel):
    mode: str
    total_regions: int
    healthy_regions: list[str] = Field(default_factory=list)
    writable_regions: list[str] = Field(default_factory=list)
    readable_regions: list[str] = Field(default_factory=list)
    active_active_ready: bool
    primary_region: str | None = None
    updated_at: float


class RegionalFailoverPolicyUpsertRequest(APIPayloadModel):
    primary_region: str
    secondary_region: str
    read_traffic_percent: dict[str, float] = Field(default_factory=dict)
    write_region: str | None = None
    auto_failback: bool = False


class RegionalFailoverPolicyResponse(APIPayloadModel):
    policy_id: str
    primary_region: str
    secondary_region: str
    read_traffic_percent: dict[str, float] = Field(default_factory=dict)
    write_region: str
    auto_failback: bool
    last_applied_at: float | None = None
    created_at: float
    updated_at: float


class RegionalFailoverPolicyListResponse(APIPayloadModel):
    items: list[RegionalFailoverPolicyResponse]
    total: int


class RegionalFailoverAppliedRegionResponse(APIPayloadModel):
    region_id: str
    read_percent: float
    read_enabled: bool
    write_enabled: bool


class RegionalFailoverApplyResponse(APIPayloadModel):
    policy_id: str
    write_region: str
    initiated_by: str
    applied_at: float
    applied_regions: list[RegionalFailoverAppliedRegionResponse] = Field(default_factory=list)


class RegionalFailoverExecuteRequest(APIPayloadModel):
    policy_id: str
    target_region: str
    reason: str


class RegionalFailoverRecoverRequest(APIPayloadModel):
    policy_id: str
    reason: str


class RegionalFailoverStatusResponse(APIPayloadModel):
    policy_id: str
    active: bool
    target_region: str | None = None
    reason: str | None = None
    initiated_by: str | None = None
    recovered_by: str | None = None
    started_at: float | None = None
    resolved_at: float | None = None
    updated_at: float


class CostAwareModelProfileUpsertRequest(APIPayloadModel):
    model_id: str
    region: str
    cost_per_1k_tokens: float = Field(ge=0.0)
    latency_ms: float = Field(ge=0.0)
    queue_depth: int = Field(ge=0)
    quality_score: float = Field(ge=0.0, le=1.0)


class CostAwareWorkerProfileUpsertRequest(APIPayloadModel):
    worker_pool: str
    region: str
    cost_per_minute: float = Field(ge=0.0)
    latency_ms: float = Field(ge=0.0)
    queue_depth: int = Field(ge=0)
    reliability_score: float = Field(ge=0.0, le=1.0)


class CostAwareModelProfileResponse(APIPayloadModel):
    candidate_id: str
    model_id: str
    region: str
    cost_per_1k_tokens: float
    latency_ms: float
    queue_depth: int
    quality_score: float
    updated_at: float


class CostAwareWorkerProfileResponse(APIPayloadModel):
    candidate_id: str
    worker_pool: str
    region: str
    cost_per_minute: float
    latency_ms: float
    queue_depth: int
    reliability_score: float
    updated_at: float


class CostAwareModelProfileListResponse(APIPayloadModel):
    items: list[CostAwareModelProfileResponse]
    total: int


class CostAwareWorkerProfileListResponse(APIPayloadModel):
    items: list[CostAwareWorkerProfileResponse]
    total: int


class CostAwareScheduleRequest(APIPayloadModel):
    tenant_id: str | None = None
    objective: str = "balanced"


class CostAwareScheduleDecisionResponse(APIPayloadModel):
    tenant_id: str
    objective: str
    selected_candidate: str
    route_type: str
    selected_resource: str
    region: str
    score: float
    routed_at: float
    rationale: dict[str, float | int]


class GovernancePolicyUpsertRequest(APIPayloadModel):
    consent_required: bool = False
    allowed_target_patterns: list[str] = Field(default_factory=list)


class GovernancePolicyResponse(APIPayloadModel):
    tenant_id: str
    consent_required: bool
    allowed_target_patterns: list[str] = Field(default_factory=list)
    created_at: float
    updated_at: float


class GovernancePolicyListResponse(APIPayloadModel):
    items: list[GovernancePolicyResponse]
    total: int


class GovernanceEvaluateRequest(APIPayloadModel):
    tenant_id: str | None = None
    action_type: str
    target: str | None = None
    consent_granted: bool = False


class GovernanceEvaluationResponse(APIPayloadModel):
    tenant_id: str
    action_type: str
    target: str | None = None
    consent_granted: bool
    allowed: bool
    reason: str
    matched_pattern: str | None = None
    allowed_target_patterns: list[str] = Field(default_factory=list)
    evaluated_at: float


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


class PolicyDecisionEvaluateRequest(APIPayloadModel):
    actor_id: str
    site_id: str
    region_allowed: bool
    has_authorization: bool
    risk_score: float = Field(ge=0.0, le=1.0)
    action: str
    jurisdiction: str = "global"
    metadata: dict[str, str] = Field(default_factory=dict)
    simulate: bool = False


class PolicyExplanationResponse(APIPayloadModel):
    rule_id: str
    priority: int
    verdict: str
    reason: str


class PolicyDecisionResponse(APIPayloadModel):
    decision_id: str
    tenant_id: str
    actor_id: str
    site_id: str
    region_allowed: bool
    has_authorization: bool
    risk_score: float
    action: str
    jurisdiction: str
    metadata: dict[str, str] = Field(default_factory=dict)
    simulate: bool
    allowed: bool
    would_allow: bool | None = None
    reason: str
    applied_rule_id: str | None = None
    created_at: float
    explanations: list[PolicyExplanationResponse] = Field(default_factory=list)


class PolicyDecisionListResponse(APIPayloadModel):
    items: list[PolicyDecisionResponse]
    total: int


class PolicyDecisionSnapshotResponse(APIPayloadModel):
    items: list[PolicyDecisionResponse]
    total: int
    selected: PolicyDecisionResponse | None = None


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
    site_pack_registry_store_type = os.getenv("SITE_PACK_REGISTRY_STORE", "memory").strip().lower()
    site_pack_registry_file_path = os.getenv("SITE_PACK_REGISTRY_FILE_PATH", "")
    site_pack_active_channel = os.getenv("SITE_PACK_ACTIVE_CHANNEL", "dev").strip().lower() or "dev"
    site_pack_auto_apply = os.getenv("SITE_PACK_AUTO_APPLY", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    feature_flag_store_type = os.getenv("FEATURE_FLAG_STORE", "memory").strip().lower()
    feature_flag_file_path = os.getenv("FEATURE_FLAG_FILE_PATH", "")
    usage_metering_store_type = os.getenv("USAGE_METERING_STORE", "memory").strip().lower()
    usage_metering_file_path = os.getenv("USAGE_METERING_FILE_PATH", "")
    cost_aware_scheduler_store_type = os.getenv("COST_AWARE_SCHEDULER_STORE", "memory").strip().lower()
    cost_aware_scheduler_file_path = os.getenv("COST_AWARE_SCHEDULER_FILE_PATH", "")
    billing_store_type = os.getenv("BILLING_STORE", "memory").strip().lower()
    billing_file_path = os.getenv("BILLING_FILE_PATH", "")
    billing_enforcement_enabled = os.getenv("BILLING_ENFORCEMENT_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    data_residency_store_type = os.getenv("DATA_RESIDENCY_STORE", "memory").strip().lower()
    data_residency_file_path = os.getenv("DATA_RESIDENCY_FILE_PATH", "")
    data_residency_enforcement_enabled = os.getenv("DATA_RESIDENCY_ENFORCEMENT_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    data_residency_default_region = os.getenv("DATA_RESIDENCY_DEFAULT_REGION", "global").strip().lower() or "global"
    multi_region_control_plane_store_type = os.getenv("MULTI_REGION_CONTROL_PLANE_STORE", "memory").strip().lower()
    multi_region_control_plane_file_path = os.getenv("MULTI_REGION_CONTROL_PLANE_FILE_PATH", "")
    regional_failover_store_type = os.getenv("REGIONAL_FAILOVER_STORE", "memory").strip().lower()
    regional_failover_file_path = os.getenv("REGIONAL_FAILOVER_FILE_PATH", "")
    governance_policy_store_type = os.getenv("GOVERNANCE_POLICY_STORE", "memory").strip().lower()
    governance_policy_file_path = os.getenv("GOVERNANCE_POLICY_FILE_PATH", "")
    governance_enforcement_enabled = os.getenv("GOVERNANCE_ENFORCEMENT_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    drift_baseline_window = int(os.getenv("DRIFT_BASELINE_WINDOW", "20"))
    drift_recent_window = int(os.getenv("DRIFT_RECENT_WINDOW", "10"))
    drift_default_threshold = float(os.getenv("DRIFT_DEFAULT_THRESHOLD", "0.25"))
    policy_risk_threshold = float(os.getenv("POLICY_ENGINE_RISK_THRESHOLD", "0.7"))
    policy_decision_store_type = os.getenv("POLICY_DECISION_STORE", "memory").strip().lower()
    policy_decision_file_path = os.getenv("POLICY_DECISION_FILE_PATH", "")
    review_queue_store_type = os.getenv("REVIEW_QUEUE_STORE", "memory").strip().lower()
    review_queue_file_path = os.getenv("REVIEW_QUEUE_FILE_PATH", "")
    event_stream_max_events = int(os.getenv("EVENT_STREAM_MAX_EVENTS", "1000"))
    webhook_store_type = os.getenv("WEBHOOK_SUBSCRIPTION_STORE", "memory").strip().lower()
    webhook_store_file_path = os.getenv("WEBHOOK_SUBSCRIPTION_FILE_PATH", "")
    webhook_timeout_seconds = float(os.getenv("WEBHOOK_DELIVERY_TIMEOUT_SECONDS", "3"))
    operator_artifacts_file_path = os.getenv("OPERATOR_CONSOLE_ARTIFACTS_FILE_PATH", "")
    operator_queue_file_path = os.getenv("OPERATOR_CONSOLE_QUEUE_FILE_PATH", "")
    synthetic_monitoring_enabled = os.getenv("SYNTHETIC_MONITORING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    synthetic_monitoring_triton_endpoint = os.getenv("SYNTHETIC_MONITORING_TRITON_ENDPOINT", "").strip()
    synthetic_monitoring_triton_model_name = os.getenv("SYNTHETIC_MONITORING_TRITON_MODEL", "ui-detector").strip() or "ui-detector"

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

    if site_pack_registry_store_type == "file":
        if not site_pack_registry_file_path:
            raise RuntimeError("SITE_PACK_REGISTRY_FILE_PATH is required when SITE_PACK_REGISTRY_STORE=file")
        site_pack_registry_store = JsonFileSitePackRegistryStore(site_pack_registry_file_path)
    else:
        site_pack_registry_store = InMemorySitePackRegistryStore()

    if feature_flag_store_type == "file":
        if not feature_flag_file_path:
            raise RuntimeError("FEATURE_FLAG_FILE_PATH is required when FEATURE_FLAG_STORE=file")
        feature_flag_store = JsonFileFeatureFlagStore(feature_flag_file_path)
    else:
        feature_flag_store = InMemoryFeatureFlagStore()

    if usage_metering_store_type == "file":
        if not usage_metering_file_path:
            raise RuntimeError("USAGE_METERING_FILE_PATH is required when USAGE_METERING_STORE=file")
        usage_metering_store = JsonFileUsageMeteringStore(usage_metering_file_path)
    else:
        usage_metering_store = InMemoryUsageMeteringStore()

    if cost_aware_scheduler_store_type == "file":
        if not cost_aware_scheduler_file_path:
            raise RuntimeError("COST_AWARE_SCHEDULER_FILE_PATH is required when COST_AWARE_SCHEDULER_STORE=file")
        cost_aware_scheduler_store = JsonFileCostAwareSchedulerStore(cost_aware_scheduler_file_path)
    else:
        cost_aware_scheduler_store = InMemoryCostAwareSchedulerStore()

    if billing_store_type == "file":
        if not billing_file_path:
            raise RuntimeError("BILLING_FILE_PATH is required when BILLING_STORE=file")
        billing_store = JsonFileBillingStore(billing_file_path)
    else:
        billing_store = InMemoryBillingStore()

    if data_residency_store_type == "file":
        if not data_residency_file_path:
            raise RuntimeError("DATA_RESIDENCY_FILE_PATH is required when DATA_RESIDENCY_STORE=file")
        data_residency_store = JsonFileDataResidencyStore(data_residency_file_path)
    else:
        data_residency_store = InMemoryDataResidencyStore()

    if multi_region_control_plane_store_type == "file":
        if not multi_region_control_plane_file_path:
            raise RuntimeError(
                "MULTI_REGION_CONTROL_PLANE_FILE_PATH is required when MULTI_REGION_CONTROL_PLANE_STORE=file"
            )
        multi_region_control_plane_store = JsonFileMultiRegionControlPlaneStore(multi_region_control_plane_file_path)
    else:
        multi_region_control_plane_store = InMemoryMultiRegionControlPlaneStore()

    if regional_failover_store_type == "file":
        if not regional_failover_file_path:
            raise RuntimeError("REGIONAL_FAILOVER_FILE_PATH is required when REGIONAL_FAILOVER_STORE=file")
        regional_failover_store = JsonFileRegionalFailoverStore(regional_failover_file_path)
    else:
        regional_failover_store = InMemoryRegionalFailoverStore()

    if governance_policy_store_type == "file":
        if not governance_policy_file_path:
            raise RuntimeError("GOVERNANCE_POLICY_FILE_PATH is required when GOVERNANCE_POLICY_STORE=file")
        governance_policy_store = JsonFileGovernancePolicyStore(governance_policy_file_path)
    else:
        governance_policy_store = InMemoryGovernancePolicyStore()

    if policy_decision_store_type == "file":
        if not policy_decision_file_path:
            raise RuntimeError("POLICY_DECISION_FILE_PATH is required when POLICY_DECISION_STORE=file")
        policy_decision_store = JsonFilePolicyDecisionStore(policy_decision_file_path)
    else:
        policy_decision_store = InMemoryPolicyDecisionStore()

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
    site_pack_registry = SitePackRegistry(store=site_pack_registry_store)
    feature_flags = FeatureFlagService(store=feature_flag_store)
    usage_metering = TenantUsageMetering(store=usage_metering_store)
    cost_aware_scheduler = CostAwareScheduler(store=cost_aware_scheduler_store)
    billing = BillingPrimitives(store=billing_store)
    data_residency = TenantDataResidencyPolicyService(store=data_residency_store)
    multi_region_control_plane = MultiRegionControlPlaneService(store=multi_region_control_plane_store)
    regional_failover = RegionalFailoverOrchestrator(
        control_plane=multi_region_control_plane,
        store=regional_failover_store,
    )
    governance_controls = ConsentTargetGovernanceService(store=governance_policy_store)
    drift_monitor = DriftMonitor(
        baseline_window=drift_baseline_window,
        recent_window=drift_recent_window,
        default_threshold=drift_default_threshold,
    )
    policy_explorer = PolicyDecisionExplorer(
        risk_threshold=policy_risk_threshold,
        store=policy_decision_store,
    )
    review_queue = HumanReviewQueue(store=review_queue_store)
    event_broker = EventStreamBroker(max_events=event_stream_max_events)
    api_tracer = OpenTelemetryTracer(component="api")
    orchestrator_tracer = OpenTelemetryTracer(component="orchestrator")
    audit_sink = build_audit_export_sink_from_env()
    webhook_publisher = LifecycleEventWebhookPublisher(store=webhook_store, timeout_seconds=webhook_timeout_seconds)
    engine = ExecutionEngine(orchestrator=DecisionOrchestrator(tracer=orchestrator_tracer))
    metrics = InMemoryMetrics()

    def _api_synthetic_probe() -> None:
        # Ensure a stable core API snapshot path remains responsive.
        _ = metrics.snapshot()

    def _worker_synthetic_probe() -> None:
        # Exercise orchestrator selection path to validate worker-like execution path.
        _ = engine.orchestrator.select_candidate([])

    synthetic_triton_client: TritonVisionClient | None = None
    if synthetic_monitoring_triton_endpoint:
        synthetic_triton_client = TritonVisionClient(
            TritonConfig(
                endpoint=synthetic_monitoring_triton_endpoint,
                model_name=synthetic_monitoring_triton_model_name,
                allowed_hosts=("127.0.0.1", "localhost"),
            )
        )

    synthetic_monitor = SyntheticMonitor(
        api_probe=_api_synthetic_probe,
        worker_probe=_worker_synthetic_probe,
        queue=async_job_queue,
        triton_client=synthetic_triton_client,
        triton_endpoint=synthetic_monitoring_triton_endpoint,
        triton_model_name=synthetic_monitoring_triton_model_name,
    )
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
        if path.startswith(f"{API_V1_PREFIX}/feature-flags/evaluate") or path.startswith("/feature-flags/evaluate"):
            return "operator"
        if path.startswith(f"{API_V1_PREFIX}/feature-flags") or path.startswith("/feature-flags"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/usage/metering") or path.startswith("/usage/metering"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/billing") or path.startswith("/billing"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/data-residency/validate") or path.startswith("/data-residency/validate"):
            return "operator"
        if path.startswith(f"{API_V1_PREFIX}/data-residency") or path.startswith("/data-residency"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/control-plane/route") or path.startswith("/control-plane/route"):
            return "operator"
        if path.startswith(f"{API_V1_PREFIX}/control-plane/topology") or path.startswith("/control-plane/topology"):
            return "operator"
        if path.startswith(f"{API_V1_PREFIX}/control-plane/failover/status") or path.startswith("/control-plane/failover/status"):
            return "operator"
        if path.startswith(f"{API_V1_PREFIX}/control-plane/failover") or path.startswith("/control-plane/failover"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/control-plane") or path.startswith("/control-plane"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/scheduler/cost-aware/route") or path.startswith("/scheduler/cost-aware/route"):
            return "operator"
        if path.startswith(f"{API_V1_PREFIX}/scheduler/cost-aware") or path.startswith("/scheduler/cost-aware"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/governance/evaluate") or path.startswith("/governance/evaluate"):
            return "operator"
        if path.startswith(f"{API_V1_PREFIX}/governance") or path.startswith("/governance"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/events/subscriptions") or path.startswith("/events/subscriptions"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/models/registry") or path.startswith("/models/registry"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/site-packs") or path.startswith("/site-packs"):
            return "admin"
        if path.startswith(f"{API_V1_PREFIX}/monitoring/synthetic") or path.startswith("/monitoring/synthetic"):
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

    def _to_cost_aware_model_profile_response(payload: dict[str, Any]) -> CostAwareModelProfileResponse:
        return CostAwareModelProfileResponse(
            candidate_id=str(payload.get("candidate_id", "")),
            model_id=str(payload.get("model_id", "")),
            region=str(payload.get("region", "")),
            cost_per_1k_tokens=float(payload.get("cost_per_1k_tokens", 0.0)),
            latency_ms=float(payload.get("latency_ms", 0.0)),
            queue_depth=int(payload.get("queue_depth", 0)),
            quality_score=float(payload.get("quality_score", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _to_cost_aware_worker_profile_response(payload: dict[str, Any]) -> CostAwareWorkerProfileResponse:
        return CostAwareWorkerProfileResponse(
            candidate_id=str(payload.get("candidate_id", "")),
            worker_pool=str(payload.get("worker_pool", "")),
            region=str(payload.get("region", "")),
            cost_per_minute=float(payload.get("cost_per_minute", 0.0)),
            latency_ms=float(payload.get("latency_ms", 0.0)),
            queue_depth=int(payload.get("queue_depth", 0)),
            reliability_score=float(payload.get("reliability_score", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _upsert_cost_aware_model_profile(
        candidate_id: str,
        payload: CostAwareModelProfileUpsertRequest,
    ) -> CostAwareModelProfileResponse:
        try:
            profile = cost_aware_scheduler.upsert_model_profile(
                candidate_id=candidate_id,
                model_id=payload.model_id,
                region=payload.region,
                cost_per_1k_tokens=payload.cost_per_1k_tokens,
                latency_ms=payload.latency_ms,
                queue_depth=payload.queue_depth,
                quality_score=payload.quality_score,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_cost_aware_model_profile_response(profile)

    def _upsert_cost_aware_worker_profile(
        candidate_id: str,
        payload: CostAwareWorkerProfileUpsertRequest,
    ) -> CostAwareWorkerProfileResponse:
        try:
            profile = cost_aware_scheduler.upsert_worker_profile(
                candidate_id=candidate_id,
                worker_pool=payload.worker_pool,
                region=payload.region,
                cost_per_minute=payload.cost_per_minute,
                latency_ms=payload.latency_ms,
                queue_depth=payload.queue_depth,
                reliability_score=payload.reliability_score,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_cost_aware_worker_profile_response(profile)

    def _list_cost_aware_model_profiles() -> CostAwareModelProfileListResponse:
        items = [
            _to_cost_aware_model_profile_response(item)
            for item in cost_aware_scheduler.list_model_profiles()
        ]
        return CostAwareModelProfileListResponse(items=items, total=len(items))

    def _list_cost_aware_worker_profiles() -> CostAwareWorkerProfileListResponse:
        items = [
            _to_cost_aware_worker_profile_response(item)
            for item in cost_aware_scheduler.list_worker_profiles()
        ]
        return CostAwareWorkerProfileListResponse(items=items, total=len(items))

    def _schedule_cost_aware_model(payload: CostAwareScheduleRequest, request: Request) -> CostAwareScheduleDecisionResponse:
        caller_tenant = _tenant_id(request)
        requested_tenant = payload.tenant_id.strip() if payload.tenant_id is not None else ""
        if requested_tenant and requested_tenant != caller_tenant:
            raise HTTPException(status_code=403, detail="tenant override does not match caller scope")

        resolved_tenant = requested_tenant or caller_tenant
        try:
            scheduled = cost_aware_scheduler.schedule_model(
                tenant_id=resolved_tenant,
                objective=payload.objective,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        rationale = {
            str(key): value
            for key, value in dict(scheduled.get("rationale", {})).items()
            if isinstance(value, (int, float))
        }
        return CostAwareScheduleDecisionResponse(
            tenant_id=str(scheduled.get("tenant_id", resolved_tenant)),
            objective=str(scheduled.get("objective", payload.objective)),
            selected_candidate=str(scheduled.get("selected_candidate", "")),
            route_type="model",
            selected_resource=str(scheduled.get("model_id", "")),
            region=str(scheduled.get("region", "")),
            score=float(scheduled.get("score", 0.0)),
            routed_at=float(scheduled.get("routed_at", time.time())),
            rationale=rationale,
        )

    def _schedule_cost_aware_worker(payload: CostAwareScheduleRequest, request: Request) -> CostAwareScheduleDecisionResponse:
        caller_tenant = _tenant_id(request)
        requested_tenant = payload.tenant_id.strip() if payload.tenant_id is not None else ""
        if requested_tenant and requested_tenant != caller_tenant:
            raise HTTPException(status_code=403, detail="tenant override does not match caller scope")

        resolved_tenant = requested_tenant or caller_tenant
        try:
            scheduled = cost_aware_scheduler.schedule_worker(
                tenant_id=resolved_tenant,
                objective=payload.objective,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        rationale = {
            str(key): value
            for key, value in dict(scheduled.get("rationale", {})).items()
            if isinstance(value, (int, float))
        }
        return CostAwareScheduleDecisionResponse(
            tenant_id=str(scheduled.get("tenant_id", resolved_tenant)),
            objective=str(scheduled.get("objective", payload.objective)),
            selected_candidate=str(scheduled.get("selected_candidate", "")),
            route_type="worker",
            selected_resource=str(scheduled.get("worker_pool", "")),
            region=str(scheduled.get("region", "")),
            score=float(scheduled.get("score", 0.0)),
            routed_at=float(scheduled.get("routed_at", time.time())),
            rationale=rationale,
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

    def _register_site_pack_version(payload: SitePackRegisterRequest) -> dict[str, Any]:
        try:
            return site_pack_registry.register_version(
                pack_id=payload.pack_id,
                version=payload.version,
                strategy_class=payload.strategy_class,
                artifact_uri=payload.artifact_uri,
                site_ids=payload.site_ids,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def _list_site_pack_versions(pack_id: str | None = None) -> SitePackVersionListResponse:
        items = site_pack_registry.list_versions(pack_id=pack_id)
        return SitePackVersionListResponse(items=items, total=len(items))

    def _apply_site_pack_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
        strategy_class = str(assignment.get("strategy_class", "")).strip()
        if not strategy_class:
            raise ValueError("strategy_class must not be empty")

        raw_site_ids = assignment.get("site_ids", [])
        site_ids = [str(item).strip() for item in raw_site_ids if str(item).strip()] if isinstance(raw_site_ids, list) else []
        if not site_ids:
            fallback_site = str(assignment.get("pack_id", "")).strip()
            if fallback_site:
                site_ids = [fallback_site]
        if not site_ids:
            raise ValueError("site_ids must contain at least one site")

        for site_id in site_ids:
            engine.orchestrator.strategy_registry.register_class(site_id, strategy_class)

        payload = dict(assignment)
        payload["applied_site_ids"] = site_ids
        return payload

    def _promote_site_pack_channel(channel: str, payload: SitePackPromotionRequest) -> SitePackPromotionResponse:
        normalized_channel = channel.strip().lower()
        try:
            assignment = site_pack_registry.promote(
                channel=normalized_channel,
                pack_id=payload.pack_id,
                version=payload.version,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="site pack version is not registered") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if site_pack_auto_apply and normalized_channel == site_pack_active_channel:
            try:
                assignment = _apply_site_pack_assignment(assignment)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return SitePackPromotionResponse(assignment=assignment)

    def _apply_site_pack_channel(channel: str) -> SitePackPromotionResponse:
        normalized_channel = channel.strip().lower()
        assignment = site_pack_registry.list_channels().get(normalized_channel)
        if assignment is None:
            raise HTTPException(status_code=404, detail="site pack channel assignment not found")

        try:
            applied = _apply_site_pack_assignment(assignment)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return SitePackPromotionResponse(assignment=applied)

    def _site_pack_runtime_mapping() -> SitePackRuntimeStrategyMapResponse:
        return SitePackRuntimeStrategyMapResponse(mappings=engine.orchestrator.strategy_registry.strategy_mapping())

    if site_pack_auto_apply:
        active_assignment = site_pack_registry.list_channels().get(site_pack_active_channel)
        if isinstance(active_assignment, dict):
            try:
                _apply_site_pack_assignment(active_assignment)
            except ValueError:
                pass

    def _to_feature_flag_response(payload: dict[str, Any]) -> FeatureFlagResponse:
        return FeatureFlagResponse(
            flag_key=str(payload.get("flag_key", "")),
            description=str(payload.get("description", "")),
            enabled=bool(payload.get("enabled", False)),
            rollout_percentage=int(payload.get("rollout_percentage", 0)),
            tenant_allowlist=[str(item) for item in payload.get("tenant_allowlist", []) if isinstance(item, str)],
            subject_allowlist=[str(item) for item in payload.get("subject_allowlist", []) if isinstance(item, str)],
            metadata={
                str(key): str(value)
                for key, value in dict(payload.get("metadata", {})).items()
            },
            created_at=float(payload.get("created_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _upsert_feature_flag(payload: FeatureFlagUpsertRequest) -> FeatureFlagResponse:
        try:
            flag = feature_flags.upsert(
                flag_key=payload.flag_key,
                description=payload.description,
                enabled=payload.enabled,
                rollout_percentage=payload.rollout_percentage,
                tenant_allowlist=payload.tenant_allowlist,
                subject_allowlist=payload.subject_allowlist,
                metadata=payload.metadata,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_feature_flag_response(flag)

    def _list_feature_flags() -> FeatureFlagListResponse:
        items = [_to_feature_flag_response(item) for item in feature_flags.list()]
        return FeatureFlagListResponse(items=items, total=len(items))

    def _get_feature_flag(flag_key: str) -> FeatureFlagResponse:
        try:
            payload = feature_flags.get(flag_key=flag_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="feature flag not found") from exc
        return _to_feature_flag_response(payload)

    def _delete_feature_flag(flag_key: str) -> FeatureFlagDeleteResponse:
        try:
            deleted = feature_flags.delete(flag_key=flag_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="feature flag not found") from exc
        return FeatureFlagDeleteResponse(flag_key=str(deleted.get("flag_key", flag_key)), deleted=True)

    def _evaluate_feature_flag(
        payload: FeatureFlagEvaluationRequest,
        *,
        tenant_id: str,
    ) -> FeatureFlagEvaluationResponse:
        if payload.tenant_id is not None and payload.tenant_id.strip() and payload.tenant_id.strip() != tenant_id:
            raise HTTPException(status_code=403, detail="tenant override does not match caller scope")
        target_tenant = payload.tenant_id.strip() if payload.tenant_id is not None else tenant_id
        if not target_tenant:
            target_tenant = tenant_id
        try:
            result = feature_flags.evaluate(
                flag_key=payload.flag_key,
                subject_key=payload.subject_key,
                tenant_id=target_tenant,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="feature flag not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return FeatureFlagEvaluationResponse(
            flag_key=str(result.get("flag_key", payload.flag_key)),
            subject_key=str(result.get("subject_key", payload.subject_key)),
            tenant_id=str(result.get("tenant_id", target_tenant)),
            enabled=bool(result.get("enabled", False)),
            reason=str(result.get("reason", "unknown")),
            bucket=(None if result.get("bucket") is None else int(result.get("bucket"))),
            rollout_percentage=int(result.get("rollout_percentage", 0)),
            matched_allowlist=bool(result.get("matched_allowlist", False)),
            evaluated_at=float(result.get("evaluated_at", time.time())),
        )

    def _to_usage_record_response(payload: dict[str, Any]) -> UsageRecordResponse:
        return UsageRecordResponse(
            record_key=str(payload.get("record_key", "")),
            tenant_id=str(payload.get("tenant_id", default_tenant)),
            dimension=str(payload.get("dimension", "")),
            day_bucket=int(payload.get("day_bucket", 0)),
            units=float(payload.get("units", 0.0)),
            created_at=float(payload.get("created_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _record_usage_metering(
        *,
        tenant_id: str,
        dimension: str,
        units: float = 1.0,
    ) -> None:
        try:
            usage_metering.record(tenant_id=tenant_id, dimension=dimension, units=units)
        except Exception:
            # Metering should not block control-plane operations.
            return

    def _list_usage_records(
        *,
        tenant_id: str | None,
        dimension: str | None,
        limit: int,
    ) -> UsageRecordListResponse:
        items = usage_metering.list_records(tenant_id=tenant_id, dimension=dimension, limit=limit)
        response_items = [_to_usage_record_response(item) for item in items]
        return UsageRecordListResponse(items=response_items, total=len(response_items))

    def _usage_summary(
        *,
        tenant_id: str,
        start_day: int | None,
        end_day: int | None,
    ) -> UsageSummaryResponse:
        try:
            payload = usage_metering.summarize(
                tenant_id=tenant_id,
                start_day=start_day,
                end_day=end_day,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return UsageSummaryResponse(
            tenant_id=str(payload.get("tenant_id", tenant_id)),
            start_day=(None if payload.get("start_day") is None else int(payload.get("start_day"))),
            end_day=(None if payload.get("end_day") is None else int(payload.get("end_day"))),
            dimensions={
                str(key): float(value)
                for key, value in dict(payload.get("dimensions", {})).items()
            },
            total_units=float(payload.get("total_units", 0.0)),
        )

    def _current_month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _month_day_range(month: str) -> tuple[int, int]:
        try:
            parsed = datetime.strptime(month, "%Y-%m")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="month must be in YYYY-MM format") from exc

        start_dt = datetime(parsed.year, parsed.month, 1, tzinfo=timezone.utc)
        if parsed.month == 12:
            next_month_dt = datetime(parsed.year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month_dt = datetime(parsed.year, parsed.month + 1, 1, tzinfo=timezone.utc)

        start_day = int(start_dt.timestamp()) // 86400
        end_day = (int(next_month_dt.timestamp()) // 86400) - 1
        return start_day, end_day

    def _to_billing_plan_response(payload: dict[str, Any]) -> BillingPlanResponse:
        return BillingPlanResponse(
            plan_id=str(payload.get("plan_id", "")),
            description=str(payload.get("description", "")),
            included_units={
                str(key): float(value)
                for key, value in dict(payload.get("included_units", {})).items()
            },
            hard_limits=bool(payload.get("hard_limits", True)),
            overage_buffer_units={
                str(key): float(value)
                for key, value in dict(payload.get("overage_buffer_units", {})).items()
            },
            created_at=float(payload.get("created_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _to_billing_subscription_response(payload: dict[str, Any]) -> BillingSubscriptionResponse:
        return BillingSubscriptionResponse(
            tenant_id=str(payload.get("tenant_id", default_tenant)),
            plan_id=str(payload.get("plan_id", "")),
            overage_protection=bool(payload.get("overage_protection", True)),
            started_at=float(payload.get("started_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _to_billing_overage_status_response(payload: dict[str, Any]) -> BillingOverageStatusResponse:
        return BillingOverageStatusResponse(
            tenant_id=str(payload.get("tenant_id", default_tenant)),
            plan_id=(None if payload.get("plan_id") in {None, ""} else str(payload.get("plan_id"))),
            overage_protection=bool(payload.get("overage_protection", False)),
            usage_dimensions={
                str(key): float(value)
                for key, value in dict(payload.get("usage_dimensions", {})).items()
            },
            limits={
                str(key): float(value)
                for key, value in dict(payload.get("limits", {})).items()
            },
            overage_buffer_units={
                str(key): float(value)
                for key, value in dict(payload.get("overage_buffer_units", {})).items()
            },
            exceeded_dimensions={
                str(key): float(value)
                for key, value in dict(payload.get("exceeded_dimensions", {})).items()
            },
            blocked_dimensions=[str(item) for item in payload.get("blocked_dimensions", []) if isinstance(item, str)],
            blocked=bool(payload.get("blocked", False)),
            within_limits=bool(payload.get("within_limits", True)),
        )

    def _to_billing_monthly_report_response(payload: dict[str, Any]) -> BillingMonthlyReportResponse:
        return BillingMonthlyReportResponse(
            month=str(payload.get("month", _current_month())),
            generated_at=float(payload.get("generated_at", time.time())),
            **_to_billing_overage_status_response(payload).model_dump(mode="python"),
        )

    def _upsert_billing_plan(payload: BillingPlanUpsertRequest) -> BillingPlanResponse:
        try:
            plan = billing.upsert_plan(
                plan_id=payload.plan_id,
                description=payload.description,
                included_units=payload.included_units,
                hard_limits=payload.hard_limits,
                overage_buffer_units=payload.overage_buffer_units,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_billing_plan_response(plan)

    def _list_billing_plans() -> BillingPlanListResponse:
        items = [_to_billing_plan_response(item) for item in billing.list_plans()]
        return BillingPlanListResponse(items=items, total=len(items))

    def _get_billing_plan(plan_id: str) -> BillingPlanResponse:
        try:
            plan = billing.get_plan(plan_id=plan_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="billing plan not found") from exc
        return _to_billing_plan_response(plan)

    def _assign_billing_plan(tenant_id: str, payload: BillingSubscriptionAssignRequest) -> BillingSubscriptionResponse:
        try:
            subscription = billing.assign_plan(
                tenant_id=tenant_id,
                plan_id=payload.plan_id,
                overage_protection=payload.overage_protection,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="billing plan not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_billing_subscription_response(subscription)

    def _get_billing_subscription(tenant_id: str) -> BillingSubscriptionResponse:
        try:
            subscription = billing.get_subscription(tenant_id=tenant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="billing subscription not found") from exc
        return _to_billing_subscription_response(subscription)

    def _usage_dimensions_for_month(tenant_id: str, month: str) -> dict[str, float]:
        start_day, end_day = _month_day_range(month)
        summary_payload = usage_metering.summarize(
            tenant_id=tenant_id,
            start_day=start_day,
            end_day=end_day,
        )
        return {
            str(key): float(value)
            for key, value in dict(summary_payload.get("dimensions", {})).items()
        }

    def _billing_overage_status(tenant_id: str, month: str) -> BillingOverageStatusResponse:
        try:
            usage_dimensions = _usage_dimensions_for_month(tenant_id, month)
            payload = billing.check_overage(tenant_id=tenant_id, usage_dimensions=usage_dimensions)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_billing_overage_status_response(payload)

    def _billing_monthly_report(tenant_id: str, month: str) -> BillingMonthlyReportResponse:
        try:
            usage_dimensions = _usage_dimensions_for_month(tenant_id, month)
            payload = billing.monthly_report(
                tenant_id=tenant_id,
                month=month,
                usage_dimensions=usage_dimensions,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_billing_monthly_report_response(payload)

    def _billing_enforcement_response(request: Request, request_id: str, tenant_id: str) -> JSONResponse | None:
        if not billing_enforcement_enabled:
            return None

        try:
            status = _billing_overage_status(tenant_id, _current_month())
        except Exception:
            return None

        if not status.blocked:
            return None
        if "api_request" not in status.blocked_dimensions:
            return None

        response = _error_response(
            request,
            status_code=402,
            code=APIErrorCode.QUOTA_EXCEEDED,
            message="billing overage protection blocked this request",
            details=[
                {
                    "tenant_id": tenant_id,
                    "blocked_dimensions": status.blocked_dimensions,
                }
            ],
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = request_id
        return response

    def _region_from_request(request: Request) -> str:
        return request.headers.get("x-region", "").strip().lower() or data_residency_default_region

    def _to_data_residency_policy_response(payload: dict[str, Any]) -> DataResidencyPolicyResponse:
        return DataResidencyPolicyResponse(
            tenant_id=str(payload.get("tenant_id", default_tenant)),
            allowed_regions=[str(item) for item in payload.get("allowed_regions", []) if isinstance(item, str)],
            default_region=str(payload.get("default_region", data_residency_default_region)),
            created_at=float(payload.get("created_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _upsert_data_residency_policy(
        tenant_id: str,
        payload: DataResidencyPolicyUpsertRequest,
    ) -> DataResidencyPolicyResponse:
        try:
            policy = data_residency.set_policy(
                tenant_id=tenant_id,
                allowed_regions=payload.allowed_regions,
                default_region=payload.default_region,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_data_residency_policy_response(policy)

    def _get_data_residency_policy(tenant_id: str) -> DataResidencyPolicyResponse:
        try:
            policy = data_residency.get_policy(tenant_id=tenant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="data residency policy not found") from exc
        return _to_data_residency_policy_response(policy)

    def _list_data_residency_policies() -> DataResidencyPolicyListResponse:
        items = [_to_data_residency_policy_response(item) for item in data_residency.list_policies()]
        return DataResidencyPolicyListResponse(items=items, total=len(items))

    def _validate_data_residency(tenant_id: str, region: str) -> DataResidencyValidationResponse:
        try:
            payload = data_residency.validate(tenant_id=tenant_id, region=region)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return DataResidencyValidationResponse(
            tenant_id=str(payload.get("tenant_id", tenant_id)),
            region=str(payload.get("region", region)),
            allowed=bool(payload.get("allowed", True)),
            reason=str(payload.get("reason", "unknown")),
            allowed_regions=[str(item) for item in payload.get("allowed_regions", []) if isinstance(item, str)],
            default_region=(
                None
                if payload.get("default_region") in {None, ""}
                else str(payload.get("default_region"))
            ),
        )

    def _to_control_plane_region_response(payload: dict[str, Any]) -> ControlPlaneRegionResponse:
        return ControlPlaneRegionResponse(
            region_id=str(payload.get("region_id", "")),
            endpoint=str(payload.get("endpoint", "")),
            traffic_weight=float(payload.get("traffic_weight", 1.0)),
            write_enabled=bool(payload.get("write_enabled", True)),
            read_enabled=bool(payload.get("read_enabled", True)),
            priority=int(payload.get("priority", 100)),
            healthy=bool(payload.get("healthy", True)),
            health_reason=(
                None
                if payload.get("health_reason") in {None, ""}
                else str(payload.get("health_reason"))
            ),
            last_heartbeat_at=float(payload.get("last_heartbeat_at", 0.0)),
            created_at=float(payload.get("created_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _upsert_control_plane_region(
        region_id: str,
        payload: ControlPlaneRegionUpsertRequest,
    ) -> ControlPlaneRegionResponse:
        try:
            region = multi_region_control_plane.upsert_region(
                region_id=region_id,
                endpoint=payload.endpoint,
                traffic_weight=payload.traffic_weight,
                write_enabled=payload.write_enabled,
                read_enabled=payload.read_enabled,
                priority=payload.priority,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_control_plane_region_response(region)

    def _get_control_plane_region(region_id: str) -> ControlPlaneRegionResponse:
        try:
            region = multi_region_control_plane.get_region(region_id=region_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="control plane region not found") from exc
        return _to_control_plane_region_response(region)

    def _list_control_plane_regions() -> ControlPlaneRegionListResponse:
        items = [
            _to_control_plane_region_response(item)
            for item in multi_region_control_plane.list_regions()
        ]
        return ControlPlaneRegionListResponse(items=items, total=len(items))

    def _update_control_plane_region_health(
        region_id: str,
        payload: ControlPlaneRegionHealthRequest,
    ) -> ControlPlaneRegionResponse:
        try:
            region = multi_region_control_plane.update_health(
                region_id=region_id,
                healthy=payload.healthy,
                reason=payload.reason,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="control plane region not found") from exc
        return _to_control_plane_region_response(region)

    def _control_plane_topology() -> ControlPlaneTopologyResponse:
        payload = multi_region_control_plane.topology_snapshot()
        return ControlPlaneTopologyResponse(
            mode=str(payload.get("mode", "active-active")),
            total_regions=int(payload.get("total_regions", 0)),
            healthy_regions=[str(item) for item in payload.get("healthy_regions", []) if isinstance(item, str)],
            writable_regions=[str(item) for item in payload.get("writable_regions", []) if isinstance(item, str)],
            readable_regions=[str(item) for item in payload.get("readable_regions", []) if isinstance(item, str)],
            active_active_ready=bool(payload.get("active_active_ready", False)),
            primary_region=(
                None
                if payload.get("primary_region") in {None, ""}
                else str(payload.get("primary_region"))
            ),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _route_control_plane(
        payload: ControlPlaneRouteRequest,
        request: Request,
    ) -> ControlPlaneRouteResponse:
        caller_tenant = _tenant_id(request)
        requested_tenant = payload.tenant_id.strip() if payload.tenant_id is not None else ""
        if requested_tenant and requested_tenant != caller_tenant:
            raise HTTPException(status_code=403, detail="tenant override does not match caller scope")

        resolved_tenant = requested_tenant or caller_tenant
        try:
            routed = multi_region_control_plane.route(
                tenant_id=resolved_tenant,
                operation=payload.operation,
                preferred_region=payload.preferred_region,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return ControlPlaneRouteResponse(
            tenant_id=str(routed.get("tenant_id", resolved_tenant)),
            operation=str(routed.get("operation", payload.operation)),
            selected_region=str(routed.get("selected_region", "")),
            endpoint=str(routed.get("endpoint", "")),
            reason=str(routed.get("reason", "weighted_active_active_routing")),
            routed_at=float(routed.get("routed_at", time.time())),
        )

    def _to_regional_failover_policy_response(payload: dict[str, Any]) -> RegionalFailoverPolicyResponse:
        return RegionalFailoverPolicyResponse(
            policy_id=str(payload.get("policy_id", "")),
            primary_region=str(payload.get("primary_region", "")),
            secondary_region=str(payload.get("secondary_region", "")),
            read_traffic_percent={
                str(region): float(percent)
                for region, percent in dict(payload.get("read_traffic_percent", {})).items()
            },
            write_region=str(payload.get("write_region", "")),
            auto_failback=bool(payload.get("auto_failback", False)),
            last_applied_at=(
                None
                if payload.get("last_applied_at") is None
                else float(payload.get("last_applied_at"))
            ),
            created_at=float(payload.get("created_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _upsert_regional_failover_policy(
        policy_id: str,
        payload: RegionalFailoverPolicyUpsertRequest,
    ) -> RegionalFailoverPolicyResponse:
        try:
            policy = regional_failover.upsert_policy(
                policy_id=policy_id,
                primary_region=payload.primary_region,
                secondary_region=payload.secondary_region,
                read_traffic_percent=payload.read_traffic_percent,
                write_region=payload.write_region,
                auto_failback=payload.auto_failback,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_regional_failover_policy_response(policy)

    def _get_regional_failover_policy(policy_id: str) -> RegionalFailoverPolicyResponse:
        try:
            policy = regional_failover.get_policy(policy_id=policy_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="regional failover policy not found") from exc
        return _to_regional_failover_policy_response(policy)

    def _list_regional_failover_policies() -> RegionalFailoverPolicyListResponse:
        items = [
            _to_regional_failover_policy_response(item)
            for item in regional_failover.list_policies()
        ]
        return RegionalFailoverPolicyListResponse(items=items, total=len(items))

    def _to_regional_failover_apply_response(payload: dict[str, Any]) -> RegionalFailoverApplyResponse:
        return RegionalFailoverApplyResponse(
            policy_id=str(payload.get("policy_id", "")),
            write_region=str(payload.get("write_region", "")),
            initiated_by=str(payload.get("initiated_by", "")),
            applied_at=float(payload.get("applied_at", 0.0)),
            applied_regions=[
                RegionalFailoverAppliedRegionResponse(
                    region_id=str(item.get("region_id", "")),
                    read_percent=float(item.get("read_percent", 0.0)),
                    read_enabled=bool(item.get("read_enabled", False)),
                    write_enabled=bool(item.get("write_enabled", False)),
                )
                for item in payload.get("applied_regions", [])
                if isinstance(item, dict)
            ],
        )

    def _apply_regional_failover_policy(policy_id: str, request: Request) -> RegionalFailoverApplyResponse:
        initiated_by = str(getattr(request.state, "api_key_id", "")) or "unknown"
        try:
            payload = regional_failover.apply_policy(policy_id=policy_id, initiated_by=initiated_by)
        except (KeyError, ValueError) as exc:
            if isinstance(exc, KeyError):
                raise HTTPException(status_code=404, detail="regional failover policy not found") from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_regional_failover_apply_response(payload)

    def _to_regional_failover_status_response(payload: dict[str, Any]) -> RegionalFailoverStatusResponse:
        return RegionalFailoverStatusResponse(
            policy_id=str(payload.get("policy_id", "")),
            active=bool(payload.get("active", False)),
            target_region=(
                None
                if payload.get("target_region") in {None, ""}
                else str(payload.get("target_region"))
            ),
            reason=(
                None
                if payload.get("reason") in {None, ""}
                else str(payload.get("reason"))
            ),
            initiated_by=(
                None
                if payload.get("initiated_by") in {None, ""}
                else str(payload.get("initiated_by"))
            ),
            recovered_by=(
                None
                if payload.get("recovered_by") in {None, ""}
                else str(payload.get("recovered_by"))
            ),
            started_at=(
                None
                if payload.get("started_at") is None
                else float(payload.get("started_at"))
            ),
            resolved_at=(
                None
                if payload.get("resolved_at") is None
                else float(payload.get("resolved_at"))
            ),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _execute_regional_failover(
        payload: RegionalFailoverExecuteRequest,
        request: Request,
    ) -> RegionalFailoverStatusResponse:
        initiated_by = str(getattr(request.state, "api_key_id", "")) or "unknown"
        try:
            status = regional_failover.execute_failover(
                policy_id=payload.policy_id,
                target_region=payload.target_region,
                reason=payload.reason,
                initiated_by=initiated_by,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="regional failover policy not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_regional_failover_status_response(status)

    def _recover_regional_failover(
        payload: RegionalFailoverRecoverRequest,
        request: Request,
    ) -> RegionalFailoverStatusResponse:
        recovered_by = str(getattr(request.state, "api_key_id", "")) or "unknown"
        try:
            status = regional_failover.recover_failover(
                policy_id=payload.policy_id,
                reason=payload.reason,
                recovered_by=recovered_by,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="regional failover policy not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_regional_failover_status_response(status)

    def _regional_failover_status(policy_id: str) -> RegionalFailoverStatusResponse:
        try:
            status = regional_failover.status(policy_id=policy_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="regional failover policy not found") from exc
        return _to_regional_failover_status_response(status)

    def _data_residency_enforcement_response(request: Request, request_id: str, tenant_id: str) -> JSONResponse | None:
        region = _region_from_request(request)
        request.state.region = region

        if not data_residency_enforcement_enabled:
            return None

        try:
            validation = _validate_data_residency(tenant_id, region)
        except Exception:
            return None

        request.state.region = validation.region
        if validation.allowed:
            return None

        response = _error_response(
            request,
            status_code=403,
            code=APIErrorCode.FORBIDDEN,
            message="request region is not allowed by tenant data residency policy",
            details=[
                {
                    "tenant_id": tenant_id,
                    "region": validation.region,
                    "allowed_regions": validation.allowed_regions,
                }
            ],
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = request_id
        return response

    def _to_governance_policy_response(payload: dict[str, Any]) -> GovernancePolicyResponse:
        return GovernancePolicyResponse(
            tenant_id=str(payload.get("tenant_id", default_tenant)),
            consent_required=bool(payload.get("consent_required", False)),
            allowed_target_patterns=[
                str(item) for item in payload.get("allowed_target_patterns", []) if isinstance(item, str)
            ],
            created_at=float(payload.get("created_at", 0.0)),
            updated_at=float(payload.get("updated_at", 0.0)),
        )

    def _upsert_governance_policy(
        tenant_id: str,
        payload: GovernancePolicyUpsertRequest,
    ) -> GovernancePolicyResponse:
        try:
            policy = governance_controls.upsert_policy(
                tenant_id=tenant_id,
                consent_required=payload.consent_required,
                allowed_target_patterns=payload.allowed_target_patterns,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_governance_policy_response(policy)

    def _get_governance_policy(tenant_id: str) -> GovernancePolicyResponse:
        try:
            policy = governance_controls.get_policy(tenant_id=tenant_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="governance policy not found") from exc
        return _to_governance_policy_response(policy)

    def _list_governance_policies() -> GovernancePolicyListResponse:
        items = [_to_governance_policy_response(item) for item in governance_controls.list_policies()]
        return GovernancePolicyListResponse(items=items, total=len(items))

    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    def _consent_granted(request: Request, action: UIAction | None = None) -> bool:
        from_header = _coerce_bool(request.headers.get("x-consent-granted", ""))
        if action is None:
            return from_header
        from_action = _coerce_bool(action.metadata.get("consent_granted"))
        return from_header or from_action

    def _evaluate_governance(
        *,
        tenant_id: str,
        action_type: str,
        target: str | None,
        consent_granted: bool,
    ) -> GovernanceEvaluationResponse:
        try:
            payload = governance_controls.evaluate(
                tenant_id=tenant_id,
                action_type=action_type,
                target=target,
                consent_granted=consent_granted,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return GovernanceEvaluationResponse(
            tenant_id=str(payload.get("tenant_id", tenant_id)),
            action_type=str(payload.get("action_type", action_type)),
            target=(None if payload.get("target") in {None, ""} else str(payload.get("target"))),
            consent_granted=bool(payload.get("consent_granted", False)),
            allowed=bool(payload.get("allowed", True)),
            reason=str(payload.get("reason", "unknown")),
            matched_pattern=(
                None
                if payload.get("matched_pattern") in {None, ""}
                else str(payload.get("matched_pattern"))
            ),
            allowed_target_patterns=[
                str(item) for item in payload.get("allowed_target_patterns", []) if isinstance(item, str)
            ],
            evaluated_at=float(payload.get("evaluated_at", time.time())),
        )

    def _enforce_governance_or_raise(request: Request, tenant_id: str, action: UIAction) -> None:
        if not governance_enforcement_enabled:
            return

        evaluation = _evaluate_governance(
            tenant_id=tenant_id,
            action_type=action.action_type.value,
            target=action.target,
            consent_granted=_consent_granted(request, action),
        )
        if evaluation.allowed:
            return

        _append_audit_event(
            request,
            action="governance.enforcement.denied",
            resource_type="governance_policy",
            resource_id=tenant_id,
            details={
                "reason": evaluation.reason,
                "action_type": evaluation.action_type,
                "target": evaluation.target,
            },
        )
        raise HTTPException(status_code=403, detail=f"governance policy denied action: {evaluation.reason}")

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

    def _to_policy_explanation_response(payload: dict[str, Any]) -> PolicyExplanationResponse:
        return PolicyExplanationResponse(
            rule_id=str(payload.get("rule_id", "")),
            priority=int(payload.get("priority", 0)),
            verdict=str(payload.get("verdict", "")),
            reason=str(payload.get("reason", "")),
        )

    def _to_policy_decision_response(payload: dict[str, Any]) -> PolicyDecisionResponse:
        return PolicyDecisionResponse(
            decision_id=str(payload.get("decision_id", "")),
            tenant_id=str(payload.get("tenant_id", default_tenant)),
            actor_id=str(payload.get("actor_id", "")),
            site_id=str(payload.get("site_id", "")),
            region_allowed=bool(payload.get("region_allowed", False)),
            has_authorization=bool(payload.get("has_authorization", False)),
            risk_score=float(payload.get("risk_score", 0.0)),
            action=str(payload.get("action", "")),
            jurisdiction=str(payload.get("jurisdiction", "global")),
            metadata={
                str(key): str(value)
                for key, value in dict(payload.get("metadata", {})).items()
            },
            simulate=bool(payload.get("simulate", False)),
            allowed=bool(payload.get("allowed", False)),
            would_allow=(
                None
                if payload.get("would_allow") is None
                else bool(payload.get("would_allow"))
            ),
            reason=str(payload.get("reason", "")),
            applied_rule_id=(
                None
                if payload.get("applied_rule_id") is None
                else str(payload.get("applied_rule_id"))
            ),
            created_at=float(payload.get("created_at", 0.0)),
            explanations=[
                _to_policy_explanation_response(item)
                for item in payload.get("explanations", [])
                if isinstance(item, dict)
            ],
        )

    def _evaluate_policy_decision(
        payload: PolicyDecisionEvaluateRequest,
        *,
        tenant_id: str,
    ) -> PolicyDecisionResponse:
        try:
            decision = policy_explorer.evaluate(
                tenant_id=tenant_id,
                actor_id=payload.actor_id,
                site_id=payload.site_id,
                region_allowed=payload.region_allowed,
                has_authorization=payload.has_authorization,
                risk_score=payload.risk_score,
                action=payload.action,
                jurisdiction=payload.jurisdiction,
                metadata=payload.metadata,
                simulate=payload.simulate,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _to_policy_decision_response(decision)

    def _list_policy_decisions(
        *,
        tenant_id: str,
        allowed: bool | None,
        limit: int,
    ) -> PolicyDecisionListResponse:
        items = policy_explorer.list(tenant_id=tenant_id, allowed=allowed, limit=limit)
        response_items = [_to_policy_decision_response(item) for item in items]
        return PolicyDecisionListResponse(items=response_items, total=len(response_items))

    def _get_policy_decision(*, decision_id: str, tenant_id: str) -> PolicyDecisionResponse:
        try:
            payload = policy_explorer.get(decision_id=decision_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="policy decision not found") from exc

        if str(payload.get("tenant_id", default_tenant)) != tenant_id:
            raise HTTPException(status_code=404, detail="policy decision not found")
        return _to_policy_decision_response(payload)

    def _build_policy_snapshot(
        *,
        tenant_id: str,
        allowed: bool | None,
        limit: int,
        decision_id: str | None,
    ) -> PolicyDecisionSnapshotResponse:
        listing = _list_policy_decisions(tenant_id=tenant_id, allowed=allowed, limit=limit)
        selected: PolicyDecisionResponse | None = None
        if decision_id:
            try:
                selected = _get_policy_decision(decision_id=decision_id, tenant_id=tenant_id)
            except HTTPException:
                selected = None

        if selected is None and listing.items:
            selected = listing.items[0]

        return PolicyDecisionSnapshotResponse(items=listing.items, total=listing.total, selected=selected)

    def _render_policy_explorer(snapshot: PolicyDecisionSnapshotResponse) -> str:
        selected_id = ""
        if snapshot.selected is not None:
            selected_id = snapshot.selected.decision_id

        table_rows = "".join(
            (
                f"<tr{' class=\'selected\'' if item.decision_id == selected_id else ''}>"
                f"<td><a href='?decision_id={html.escape(item.decision_id)}'>{html.escape(item.decision_id)}</a></td>"
                f"<td>{'allow' if item.allowed else 'deny'}</td>"
                f"<td>{html.escape(item.actor_id)}</td>"
                f"<td>{html.escape(item.site_id)}</td>"
                f"<td>{html.escape(item.reason)}</td>"
                "</tr>"
            )
            for item in snapshot.items
        ) or "<tr><td colspan='5'>No decisions</td></tr>"

        explanation_rows = ""
        selected_payload = "{}"
        if snapshot.selected is not None:
            explanation_rows = "".join(
                (
                    "<tr>"
                    f"<td>{html.escape(item.rule_id)}</td>"
                    f"<td>{item.priority}</td>"
                    f"<td>{html.escape(item.verdict)}</td>"
                    f"<td>{html.escape(item.reason)}</td>"
                    "</tr>"
                )
                for item in snapshot.selected.explanations
            ) or "<tr><td colspan='4'>No explanations</td></tr>"
            selected_payload = html.escape(
                json.dumps(snapshot.selected.model_dump(mode="json"), indent=2, sort_keys=True)
            )
        else:
            explanation_rows = "<tr><td colspan='4'>No decision selected</td></tr>"

        return f"""<!doctype html>
<html lang='en'>
<head>
    <meta charset='utf-8' />
    <title>Project Mimic Policy Explorer</title>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 24px; background: #0b1020; color: #e8edf7; }}
        h1, h2 {{ color: #f5f7ff; }}
        section {{ background: #121a31; border: 1px solid #24314f; border-radius: 12px; padding: 16px; margin-bottom: 16px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ text-align: left; border-bottom: 1px solid #24314f; padding: 8px; vertical-align: top; }}
        tr.selected {{ background: #1a2742; }}
        a {{ color: #7dc7ff; text-decoration: none; }}
        pre {{ overflow: auto; background: #09101f; padding: 12px; border-radius: 8px; }}
        .muted {{ color: #a9b4cc; }}
    </style>
</head>
<body>
    <h1>Policy Decision Explorer</h1>
    <p class='muted'>Review policy outcomes with rule-by-rule explanation trails</p>
    <section>
        <h2>Recent Decisions ({snapshot.total})</h2>
        <table>
            <thead><tr><th>Decision ID</th><th>Outcome</th><th>Actor</th><th>Site</th><th>Reason</th></tr></thead>
            <tbody>{table_rows}</tbody>
        </table>
    </section>
    <section>
        <h2>Explanation Trail</h2>
        <table>
            <thead><tr><th>Rule</th><th>Priority</th><th>Verdict</th><th>Reason</th></tr></thead>
            <tbody>{explanation_rows}</tbody>
        </table>
    </section>
    <section>
        <h2>Selected Decision JSON</h2>
        <pre>{selected_payload}</pre>
    </section>
</body>
</html>"""

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

            residency_blocked = _data_residency_enforcement_response(request, request_id, _tenant_id(request))
            if residency_blocked is not None:
                return residency_blocked

            overage_blocked = _billing_enforcement_response(request, request_id, _tenant_id(request))
            if overage_blocked is not None:
                return overage_blocked

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
                _record_usage_metering(
                    tenant_id=_tenant_id(request),
                    dimension="api_request",
                    units=1.0,
                )
                return timeout_response
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        metrics.record(request.url.path, response.status_code, elapsed_ms)
        _record_usage_metering(
            tenant_id=_tenant_id(request),
            dimension="api_request",
            units=1.0,
        )
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
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="session_create", units=1.0)
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
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="session_create", units=1.0)
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
        _enforce_governance_or_raise(request, _tenant_id(request), action)
        response = _step_session(session_id, action, tenant_id=_tenant_id(request))
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="session_step", units=1.0)
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
        _enforce_governance_or_raise(request, _tenant_id(request), action)
        step_response = _step_session(session_id, action, tenant_id=_tenant_id(request))
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="session_step", units=1.0)
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
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="async_job_submit", units=1.0)
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
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="async_job_submit", units=1.0)
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

    @app.post(f"{API_V1_PREFIX}/site-packs/register")
    def register_site_pack_version_v1(
        payload: SitePackRegisterRequest,
        request: Request,
    ) -> dict[str, Any]:
        registered = _register_site_pack_version(payload)
        _append_audit_event(
            request,
            action="site_pack.registry.register",
            resource_type="site_pack_version",
            resource_id=f"{registered['pack_id']}::{registered['version']}",
        )
        _publish_realtime_event(
            event_type="site_pack.registry.registered",
            tenant_id=_tenant_id(request),
            payload={
                "pack_id": registered["pack_id"],
                "version": registered["version"],
                "strategy_class": registered["strategy_class"],
            },
        )
        return registered

    @app.post("/site-packs/register", deprecated=True)
    def register_site_pack_version_legacy(
        payload: SitePackRegisterRequest,
        response: Response,
        request: Request,
    ) -> dict[str, Any]:
        _set_deprecation_headers(response)
        registered = _register_site_pack_version(payload)
        _append_audit_event(
            request,
            action="site_pack.registry.register",
            resource_type="site_pack_version",
            resource_id=f"{registered['pack_id']}::{registered['version']}",
        )
        _publish_realtime_event(
            event_type="site_pack.registry.registered",
            tenant_id=_tenant_id(request),
            payload={
                "pack_id": registered["pack_id"],
                "version": registered["version"],
                "strategy_class": registered["strategy_class"],
            },
        )
        return registered

    @app.get(f"{API_V1_PREFIX}/site-packs/versions", response_model=SitePackVersionListResponse)
    def list_site_pack_versions_v1(pack_id: str | None = Query(default=None)) -> SitePackVersionListResponse:
        return _list_site_pack_versions(pack_id=pack_id)

    @app.get("/site-packs/versions", response_model=SitePackVersionListResponse, deprecated=True)
    def list_site_pack_versions_legacy(
        response: Response,
        pack_id: str | None = Query(default=None),
    ) -> SitePackVersionListResponse:
        _set_deprecation_headers(response)
        return _list_site_pack_versions(pack_id=pack_id)

    @app.post(f"{API_V1_PREFIX}/site-packs/channels/{{channel}}/promote", response_model=SitePackPromotionResponse)
    def promote_site_pack_channel_v1(
        channel: str,
        payload: SitePackPromotionRequest,
        request: Request,
    ) -> SitePackPromotionResponse:
        promoted = _promote_site_pack_channel(channel, payload)
        _append_audit_event(
            request,
            action="site_pack.registry.promote",
            resource_type="site_pack_channel",
            resource_id=channel,
            details=promoted.assignment,
        )
        _publish_realtime_event(
            event_type="site_pack.registry.promoted",
            tenant_id=_tenant_id(request),
            payload={
                "channel": promoted.assignment.get("channel", channel),
                "pack_id": promoted.assignment.get("pack_id", payload.pack_id),
                "version": promoted.assignment.get("version", payload.version),
            },
        )
        return promoted

    @app.post("/site-packs/channels/{channel}/promote", response_model=SitePackPromotionResponse, deprecated=True)
    def promote_site_pack_channel_legacy(
        channel: str,
        payload: SitePackPromotionRequest,
        response: Response,
        request: Request,
    ) -> SitePackPromotionResponse:
        _set_deprecation_headers(response)
        promoted = _promote_site_pack_channel(channel, payload)
        _append_audit_event(
            request,
            action="site_pack.registry.promote",
            resource_type="site_pack_channel",
            resource_id=channel,
            details=promoted.assignment,
        )
        _publish_realtime_event(
            event_type="site_pack.registry.promoted",
            tenant_id=_tenant_id(request),
            payload={
                "channel": promoted.assignment.get("channel", channel),
                "pack_id": promoted.assignment.get("pack_id", payload.pack_id),
                "version": promoted.assignment.get("version", payload.version),
            },
        )
        return promoted

    @app.post(f"{API_V1_PREFIX}/site-packs/channels/{{channel}}/apply", response_model=SitePackPromotionResponse)
    def apply_site_pack_channel_v1(channel: str, request: Request) -> SitePackPromotionResponse:
        applied = _apply_site_pack_channel(channel)
        _append_audit_event(
            request,
            action="site_pack.registry.apply",
            resource_type="site_pack_channel",
            resource_id=channel,
            details=applied.assignment,
        )
        _publish_realtime_event(
            event_type="site_pack.registry.applied",
            tenant_id=_tenant_id(request),
            payload={
                "channel": applied.assignment.get("channel", channel),
                "pack_id": applied.assignment.get("pack_id"),
                "version": applied.assignment.get("version"),
                "applied_site_ids": applied.assignment.get("applied_site_ids", []),
            },
        )
        return applied

    @app.post("/site-packs/channels/{channel}/apply", response_model=SitePackPromotionResponse, deprecated=True)
    def apply_site_pack_channel_legacy(
        channel: str,
        response: Response,
        request: Request,
    ) -> SitePackPromotionResponse:
        _set_deprecation_headers(response)
        applied = _apply_site_pack_channel(channel)
        _append_audit_event(
            request,
            action="site_pack.registry.apply",
            resource_type="site_pack_channel",
            resource_id=channel,
            details=applied.assignment,
        )
        _publish_realtime_event(
            event_type="site_pack.registry.applied",
            tenant_id=_tenant_id(request),
            payload={
                "channel": applied.assignment.get("channel", channel),
                "pack_id": applied.assignment.get("pack_id"),
                "version": applied.assignment.get("version"),
                "applied_site_ids": applied.assignment.get("applied_site_ids", []),
            },
        )
        return applied

    @app.get(f"{API_V1_PREFIX}/site-packs/channels", response_model=SitePackChannelListResponse)
    def list_site_pack_channels_v1() -> SitePackChannelListResponse:
        return SitePackChannelListResponse(channels=site_pack_registry.list_channels())

    @app.get("/site-packs/channels", response_model=SitePackChannelListResponse, deprecated=True)
    def list_site_pack_channels_legacy(response: Response) -> SitePackChannelListResponse:
        _set_deprecation_headers(response)
        return SitePackChannelListResponse(channels=site_pack_registry.list_channels())

    @app.get(f"{API_V1_PREFIX}/site-packs/runtime/strategies", response_model=SitePackRuntimeStrategyMapResponse)
    def list_site_pack_runtime_mapping_v1() -> SitePackRuntimeStrategyMapResponse:
        return _site_pack_runtime_mapping()

    @app.get("/site-packs/runtime/strategies", response_model=SitePackRuntimeStrategyMapResponse, deprecated=True)
    def list_site_pack_runtime_mapping_legacy(response: Response) -> SitePackRuntimeStrategyMapResponse:
        _set_deprecation_headers(response)
        return _site_pack_runtime_mapping()

    @app.post(f"{API_V1_PREFIX}/feature-flags", response_model=FeatureFlagResponse)
    def upsert_feature_flag_v1(
        payload: FeatureFlagUpsertRequest,
        request: Request,
    ) -> FeatureFlagResponse:
        flag = _upsert_feature_flag(payload)
        _append_audit_event(
            request,
            action="feature.flag.upsert",
            resource_type="feature_flag",
            resource_id=flag.flag_key,
            details={
                "enabled": flag.enabled,
                "rollout_percentage": flag.rollout_percentage,
            },
        )
        _publish_realtime_event(
            event_type="feature.flag.updated",
            tenant_id=_tenant_id(request),
            payload={
                "flag_key": flag.flag_key,
                "enabled": flag.enabled,
                "rollout_percentage": flag.rollout_percentage,
            },
        )
        return flag

    @app.post("/feature-flags", response_model=FeatureFlagResponse, deprecated=True)
    def upsert_feature_flag_legacy(
        payload: FeatureFlagUpsertRequest,
        response: Response,
        request: Request,
    ) -> FeatureFlagResponse:
        _set_deprecation_headers(response)
        flag = _upsert_feature_flag(payload)
        _append_audit_event(
            request,
            action="feature.flag.upsert",
            resource_type="feature_flag",
            resource_id=flag.flag_key,
            details={
                "enabled": flag.enabled,
                "rollout_percentage": flag.rollout_percentage,
            },
        )
        _publish_realtime_event(
            event_type="feature.flag.updated",
            tenant_id=_tenant_id(request),
            payload={
                "flag_key": flag.flag_key,
                "enabled": flag.enabled,
                "rollout_percentage": flag.rollout_percentage,
            },
        )
        return flag

    @app.get(f"{API_V1_PREFIX}/feature-flags", response_model=FeatureFlagListResponse)
    def list_feature_flags_v1() -> FeatureFlagListResponse:
        return _list_feature_flags()

    @app.get("/feature-flags", response_model=FeatureFlagListResponse, deprecated=True)
    def list_feature_flags_legacy(response: Response) -> FeatureFlagListResponse:
        _set_deprecation_headers(response)
        return _list_feature_flags()

    @app.get(f"{API_V1_PREFIX}/feature-flags/{{flag_key}}", response_model=FeatureFlagResponse)
    def get_feature_flag_v1(flag_key: str) -> FeatureFlagResponse:
        return _get_feature_flag(flag_key)

    @app.get("/feature-flags/{flag_key}", response_model=FeatureFlagResponse, deprecated=True)
    def get_feature_flag_legacy(flag_key: str, response: Response) -> FeatureFlagResponse:
        _set_deprecation_headers(response)
        return _get_feature_flag(flag_key)

    @app.delete(f"{API_V1_PREFIX}/feature-flags/{{flag_key}}", response_model=FeatureFlagDeleteResponse)
    def delete_feature_flag_v1(flag_key: str, request: Request) -> FeatureFlagDeleteResponse:
        deleted = _delete_feature_flag(flag_key)
        _append_audit_event(
            request,
            action="feature.flag.delete",
            resource_type="feature_flag",
            resource_id=deleted.flag_key,
        )
        _publish_realtime_event(
            event_type="feature.flag.deleted",
            tenant_id=_tenant_id(request),
            payload={"flag_key": deleted.flag_key},
        )
        return deleted

    @app.delete("/feature-flags/{flag_key}", response_model=FeatureFlagDeleteResponse, deprecated=True)
    def delete_feature_flag_legacy(
        flag_key: str,
        response: Response,
        request: Request,
    ) -> FeatureFlagDeleteResponse:
        _set_deprecation_headers(response)
        deleted = _delete_feature_flag(flag_key)
        _append_audit_event(
            request,
            action="feature.flag.delete",
            resource_type="feature_flag",
            resource_id=deleted.flag_key,
        )
        _publish_realtime_event(
            event_type="feature.flag.deleted",
            tenant_id=_tenant_id(request),
            payload={"flag_key": deleted.flag_key},
        )
        return deleted

    @app.post(f"{API_V1_PREFIX}/feature-flags/evaluate", response_model=FeatureFlagEvaluationResponse)
    def evaluate_feature_flag_v1(
        payload: FeatureFlagEvaluationRequest,
        request: Request,
    ) -> FeatureFlagEvaluationResponse:
        evaluation = _evaluate_feature_flag(payload, tenant_id=_tenant_id(request))
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="feature_flag_evaluate", units=1.0)
        _append_audit_event(
            request,
            action="feature.flag.evaluate",
            resource_type="feature_flag",
            resource_id=evaluation.flag_key,
            details={
                "enabled": evaluation.enabled,
                "reason": evaluation.reason,
                "bucket": evaluation.bucket,
            },
        )
        _publish_realtime_event(
            event_type="feature.flag.evaluated",
            tenant_id=_tenant_id(request),
            payload={
                "flag_key": evaluation.flag_key,
                "enabled": evaluation.enabled,
                "reason": evaluation.reason,
            },
        )
        return evaluation

    @app.post("/feature-flags/evaluate", response_model=FeatureFlagEvaluationResponse, deprecated=True)
    def evaluate_feature_flag_legacy(
        payload: FeatureFlagEvaluationRequest,
        response: Response,
        request: Request,
    ) -> FeatureFlagEvaluationResponse:
        _set_deprecation_headers(response)
        evaluation = _evaluate_feature_flag(payload, tenant_id=_tenant_id(request))
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="feature_flag_evaluate", units=1.0)
        _append_audit_event(
            request,
            action="feature.flag.evaluate",
            resource_type="feature_flag",
            resource_id=evaluation.flag_key,
            details={
                "enabled": evaluation.enabled,
                "reason": evaluation.reason,
                "bucket": evaluation.bucket,
            },
        )
        _publish_realtime_event(
            event_type="feature.flag.evaluated",
            tenant_id=_tenant_id(request),
            payload={
                "flag_key": evaluation.flag_key,
                "enabled": evaluation.enabled,
                "reason": evaluation.reason,
            },
        )
        return evaluation

    @app.get(f"{API_V1_PREFIX}/usage/metering/records", response_model=UsageRecordListResponse)
    def list_usage_metering_records_v1(
        request: Request,
        tenant_id: str | None = Query(default=None),
        dimension: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> UsageRecordListResponse:
        resolved_tenant = tenant_id.strip() if tenant_id is not None else _tenant_id(request)
        if not resolved_tenant:
            resolved_tenant = _tenant_id(request)
        return _list_usage_records(tenant_id=resolved_tenant, dimension=dimension, limit=limit)

    @app.get("/usage/metering/records", response_model=UsageRecordListResponse, deprecated=True)
    def list_usage_metering_records_legacy(
        request: Request,
        response: Response,
        tenant_id: str | None = Query(default=None),
        dimension: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> UsageRecordListResponse:
        _set_deprecation_headers(response)
        resolved_tenant = tenant_id.strip() if tenant_id is not None else _tenant_id(request)
        if not resolved_tenant:
            resolved_tenant = _tenant_id(request)
        return _list_usage_records(tenant_id=resolved_tenant, dimension=dimension, limit=limit)

    @app.get(f"{API_V1_PREFIX}/usage/metering/summary", response_model=UsageSummaryResponse)
    def usage_metering_summary_v1(
        request: Request,
        tenant_id: str | None = Query(default=None),
        start_day: int | None = Query(default=None, ge=0),
        end_day: int | None = Query(default=None, ge=0),
    ) -> UsageSummaryResponse:
        resolved_tenant = tenant_id.strip() if tenant_id is not None else _tenant_id(request)
        if not resolved_tenant:
            resolved_tenant = _tenant_id(request)
        return _usage_summary(tenant_id=resolved_tenant, start_day=start_day, end_day=end_day)

    @app.get("/usage/metering/summary", response_model=UsageSummaryResponse, deprecated=True)
    def usage_metering_summary_legacy(
        request: Request,
        response: Response,
        tenant_id: str | None = Query(default=None),
        start_day: int | None = Query(default=None, ge=0),
        end_day: int | None = Query(default=None, ge=0),
    ) -> UsageSummaryResponse:
        _set_deprecation_headers(response)
        resolved_tenant = tenant_id.strip() if tenant_id is not None else _tenant_id(request)
        if not resolved_tenant:
            resolved_tenant = _tenant_id(request)
        return _usage_summary(tenant_id=resolved_tenant, start_day=start_day, end_day=end_day)

    @app.post(f"{API_V1_PREFIX}/billing/plans", response_model=BillingPlanResponse)
    def upsert_billing_plan_v1(
        payload: BillingPlanUpsertRequest,
        request: Request,
    ) -> BillingPlanResponse:
        plan = _upsert_billing_plan(payload)
        _append_audit_event(
            request,
            action="billing.plan.upsert",
            resource_type="billing_plan",
            resource_id=plan.plan_id,
            details={"hard_limits": plan.hard_limits},
        )
        return plan

    @app.post("/billing/plans", response_model=BillingPlanResponse, deprecated=True)
    def upsert_billing_plan_legacy(
        payload: BillingPlanUpsertRequest,
        response: Response,
        request: Request,
    ) -> BillingPlanResponse:
        _set_deprecation_headers(response)
        plan = _upsert_billing_plan(payload)
        _append_audit_event(
            request,
            action="billing.plan.upsert",
            resource_type="billing_plan",
            resource_id=plan.plan_id,
            details={"hard_limits": plan.hard_limits},
        )
        return plan

    @app.get(f"{API_V1_PREFIX}/billing/plans", response_model=BillingPlanListResponse)
    def list_billing_plans_v1() -> BillingPlanListResponse:
        return _list_billing_plans()

    @app.get("/billing/plans", response_model=BillingPlanListResponse, deprecated=True)
    def list_billing_plans_legacy(response: Response) -> BillingPlanListResponse:
        _set_deprecation_headers(response)
        return _list_billing_plans()

    @app.get(f"{API_V1_PREFIX}/billing/plans/{{plan_id}}", response_model=BillingPlanResponse)
    def get_billing_plan_v1(plan_id: str) -> BillingPlanResponse:
        return _get_billing_plan(plan_id)

    @app.get("/billing/plans/{plan_id}", response_model=BillingPlanResponse, deprecated=True)
    def get_billing_plan_legacy(plan_id: str, response: Response) -> BillingPlanResponse:
        _set_deprecation_headers(response)
        return _get_billing_plan(plan_id)

    @app.post(f"{API_V1_PREFIX}/billing/subscriptions/{{tenant_id}}", response_model=BillingSubscriptionResponse)
    def assign_billing_subscription_v1(
        tenant_id: str,
        payload: BillingSubscriptionAssignRequest,
        request: Request,
    ) -> BillingSubscriptionResponse:
        subscription = _assign_billing_plan(tenant_id, payload)
        _append_audit_event(
            request,
            action="billing.subscription.assign",
            resource_type="billing_subscription",
            resource_id=tenant_id,
            details={"plan_id": subscription.plan_id, "overage_protection": subscription.overage_protection},
        )
        return subscription

    @app.post("/billing/subscriptions/{tenant_id}", response_model=BillingSubscriptionResponse, deprecated=True)
    def assign_billing_subscription_legacy(
        tenant_id: str,
        payload: BillingSubscriptionAssignRequest,
        response: Response,
        request: Request,
    ) -> BillingSubscriptionResponse:
        _set_deprecation_headers(response)
        subscription = _assign_billing_plan(tenant_id, payload)
        _append_audit_event(
            request,
            action="billing.subscription.assign",
            resource_type="billing_subscription",
            resource_id=tenant_id,
            details={"plan_id": subscription.plan_id, "overage_protection": subscription.overage_protection},
        )
        return subscription

    @app.get(f"{API_V1_PREFIX}/billing/subscriptions/{{tenant_id}}", response_model=BillingSubscriptionResponse)
    def get_billing_subscription_v1(tenant_id: str) -> BillingSubscriptionResponse:
        return _get_billing_subscription(tenant_id)

    @app.get("/billing/subscriptions/{tenant_id}", response_model=BillingSubscriptionResponse, deprecated=True)
    def get_billing_subscription_legacy(tenant_id: str, response: Response) -> BillingSubscriptionResponse:
        _set_deprecation_headers(response)
        return _get_billing_subscription(tenant_id)

    @app.get(f"{API_V1_PREFIX}/billing/overage/{{tenant_id}}", response_model=BillingOverageStatusResponse)
    def billing_overage_status_v1(
        tenant_id: str,
        month: str | None = Query(default=None),
    ) -> BillingOverageStatusResponse:
        return _billing_overage_status(tenant_id, month or _current_month())

    @app.get("/billing/overage/{tenant_id}", response_model=BillingOverageStatusResponse, deprecated=True)
    def billing_overage_status_legacy(
        tenant_id: str,
        response: Response,
        month: str | None = Query(default=None),
    ) -> BillingOverageStatusResponse:
        _set_deprecation_headers(response)
        return _billing_overage_status(tenant_id, month or _current_month())

    @app.get(f"{API_V1_PREFIX}/billing/reports/{{tenant_id}}", response_model=BillingMonthlyReportResponse)
    def billing_monthly_report_v1(
        tenant_id: str,
        month: str | None = Query(default=None),
    ) -> BillingMonthlyReportResponse:
        return _billing_monthly_report(tenant_id, month or _current_month())

    @app.get("/billing/reports/{tenant_id}", response_model=BillingMonthlyReportResponse, deprecated=True)
    def billing_monthly_report_legacy(
        tenant_id: str,
        response: Response,
        month: str | None = Query(default=None),
    ) -> BillingMonthlyReportResponse:
        _set_deprecation_headers(response)
        return _billing_monthly_report(tenant_id, month or _current_month())

    @app.post(f"{API_V1_PREFIX}/data-residency/{{tenant_id}}", response_model=DataResidencyPolicyResponse)
    def upsert_data_residency_policy_v1(
        tenant_id: str,
        payload: DataResidencyPolicyUpsertRequest,
        request: Request,
    ) -> DataResidencyPolicyResponse:
        policy = _upsert_data_residency_policy(tenant_id, payload)
        _append_audit_event(
            request,
            action="data_residency.policy.upsert",
            resource_type="data_residency_policy",
            resource_id=tenant_id,
            details={"allowed_regions": policy.allowed_regions, "default_region": policy.default_region},
        )
        return policy

    @app.post("/data-residency/{tenant_id}", response_model=DataResidencyPolicyResponse, deprecated=True)
    def upsert_data_residency_policy_legacy(
        tenant_id: str,
        payload: DataResidencyPolicyUpsertRequest,
        response: Response,
        request: Request,
    ) -> DataResidencyPolicyResponse:
        _set_deprecation_headers(response)
        policy = _upsert_data_residency_policy(tenant_id, payload)
        _append_audit_event(
            request,
            action="data_residency.policy.upsert",
            resource_type="data_residency_policy",
            resource_id=tenant_id,
            details={"allowed_regions": policy.allowed_regions, "default_region": policy.default_region},
        )
        return policy

    @app.get(f"{API_V1_PREFIX}/data-residency", response_model=DataResidencyPolicyListResponse)
    def list_data_residency_policies_v1() -> DataResidencyPolicyListResponse:
        return _list_data_residency_policies()

    @app.get("/data-residency", response_model=DataResidencyPolicyListResponse, deprecated=True)
    def list_data_residency_policies_legacy(response: Response) -> DataResidencyPolicyListResponse:
        _set_deprecation_headers(response)
        return _list_data_residency_policies()

    @app.get(f"{API_V1_PREFIX}/data-residency/validate", response_model=DataResidencyValidationResponse)
    def validate_data_residency_v1(
        request: Request,
        tenant_id: str | None = Query(default=None),
        region: str | None = Query(default=None),
    ) -> DataResidencyValidationResponse:
        resolved_tenant = tenant_id.strip() if tenant_id is not None else _tenant_id(request)
        if not resolved_tenant:
            resolved_tenant = _tenant_id(request)
        resolved_region = (region or _region_from_request(request)).strip().lower()
        return _validate_data_residency(resolved_tenant, resolved_region)

    @app.get("/data-residency/validate", response_model=DataResidencyValidationResponse, deprecated=True)
    def validate_data_residency_legacy(
        request: Request,
        response: Response,
        tenant_id: str | None = Query(default=None),
        region: str | None = Query(default=None),
    ) -> DataResidencyValidationResponse:
        _set_deprecation_headers(response)
        resolved_tenant = tenant_id.strip() if tenant_id is not None else _tenant_id(request)
        if not resolved_tenant:
            resolved_tenant = _tenant_id(request)
        resolved_region = (region or _region_from_request(request)).strip().lower()
        return _validate_data_residency(resolved_tenant, resolved_region)

    @app.get(f"{API_V1_PREFIX}/data-residency/{{tenant_id}}", response_model=DataResidencyPolicyResponse)
    def get_data_residency_policy_v1(tenant_id: str) -> DataResidencyPolicyResponse:
        return _get_data_residency_policy(tenant_id)

    @app.get("/data-residency/{tenant_id}", response_model=DataResidencyPolicyResponse, deprecated=True)
    def get_data_residency_policy_legacy(tenant_id: str, response: Response) -> DataResidencyPolicyResponse:
        _set_deprecation_headers(response)
        return _get_data_residency_policy(tenant_id)

    @app.post(f"{API_V1_PREFIX}/control-plane/regions/{{region_id}}", response_model=ControlPlaneRegionResponse)
    def upsert_control_plane_region_v1(
        region_id: str,
        payload: ControlPlaneRegionUpsertRequest,
        request: Request,
    ) -> ControlPlaneRegionResponse:
        region = _upsert_control_plane_region(region_id, payload)
        _append_audit_event(
            request,
            action="control_plane.region.upsert",
            resource_type="control_plane_region",
            resource_id=region.region_id,
            details={
                "endpoint": region.endpoint,
                "traffic_weight": region.traffic_weight,
                "write_enabled": region.write_enabled,
                "read_enabled": region.read_enabled,
            },
        )
        return region

    @app.post("/control-plane/regions/{region_id}", response_model=ControlPlaneRegionResponse, deprecated=True)
    def upsert_control_plane_region_legacy(
        region_id: str,
        payload: ControlPlaneRegionUpsertRequest,
        response: Response,
        request: Request,
    ) -> ControlPlaneRegionResponse:
        _set_deprecation_headers(response)
        region = _upsert_control_plane_region(region_id, payload)
        _append_audit_event(
            request,
            action="control_plane.region.upsert",
            resource_type="control_plane_region",
            resource_id=region.region_id,
            details={
                "endpoint": region.endpoint,
                "traffic_weight": region.traffic_weight,
                "write_enabled": region.write_enabled,
                "read_enabled": region.read_enabled,
            },
        )
        return region

    @app.get(f"{API_V1_PREFIX}/control-plane/regions", response_model=ControlPlaneRegionListResponse)
    def list_control_plane_regions_v1() -> ControlPlaneRegionListResponse:
        return _list_control_plane_regions()

    @app.get("/control-plane/regions", response_model=ControlPlaneRegionListResponse, deprecated=True)
    def list_control_plane_regions_legacy(response: Response) -> ControlPlaneRegionListResponse:
        _set_deprecation_headers(response)
        return _list_control_plane_regions()

    @app.get(f"{API_V1_PREFIX}/control-plane/regions/{{region_id}}", response_model=ControlPlaneRegionResponse)
    def get_control_plane_region_v1(region_id: str) -> ControlPlaneRegionResponse:
        return _get_control_plane_region(region_id)

    @app.get("/control-plane/regions/{region_id}", response_model=ControlPlaneRegionResponse, deprecated=True)
    def get_control_plane_region_legacy(region_id: str, response: Response) -> ControlPlaneRegionResponse:
        _set_deprecation_headers(response)
        return _get_control_plane_region(region_id)

    @app.post(
        f"{API_V1_PREFIX}/control-plane/regions/{{region_id}}/health",
        response_model=ControlPlaneRegionResponse,
    )
    def update_control_plane_region_health_v1(
        region_id: str,
        payload: ControlPlaneRegionHealthRequest,
        request: Request,
    ) -> ControlPlaneRegionResponse:
        region = _update_control_plane_region_health(region_id, payload)
        _append_audit_event(
            request,
            action="control_plane.region.health.update",
            resource_type="control_plane_region",
            resource_id=region.region_id,
            details={"healthy": region.healthy, "health_reason": region.health_reason},
        )
        return region

    @app.post(
        "/control-plane/regions/{region_id}/health",
        response_model=ControlPlaneRegionResponse,
        deprecated=True,
    )
    def update_control_plane_region_health_legacy(
        region_id: str,
        payload: ControlPlaneRegionHealthRequest,
        response: Response,
        request: Request,
    ) -> ControlPlaneRegionResponse:
        _set_deprecation_headers(response)
        region = _update_control_plane_region_health(region_id, payload)
        _append_audit_event(
            request,
            action="control_plane.region.health.update",
            resource_type="control_plane_region",
            resource_id=region.region_id,
            details={"healthy": region.healthy, "health_reason": region.health_reason},
        )
        return region

    @app.get(f"{API_V1_PREFIX}/control-plane/topology", response_model=ControlPlaneTopologyResponse)
    def control_plane_topology_v1() -> ControlPlaneTopologyResponse:
        return _control_plane_topology()

    @app.get("/control-plane/topology", response_model=ControlPlaneTopologyResponse, deprecated=True)
    def control_plane_topology_legacy(response: Response) -> ControlPlaneTopologyResponse:
        _set_deprecation_headers(response)
        return _control_plane_topology()

    @app.post(f"{API_V1_PREFIX}/control-plane/route", response_model=ControlPlaneRouteResponse)
    def route_control_plane_v1(payload: ControlPlaneRouteRequest, request: Request) -> ControlPlaneRouteResponse:
        routed = _route_control_plane(payload, request)
        _record_usage_metering(tenant_id=routed.tenant_id, dimension="control_plane_route", units=1.0)
        _append_audit_event(
            request,
            action="control_plane.route.evaluate",
            resource_type="control_plane_route",
            resource_id=routed.selected_region,
            details={"operation": routed.operation, "reason": routed.reason},
        )
        return routed

    @app.post("/control-plane/route", response_model=ControlPlaneRouteResponse, deprecated=True)
    def route_control_plane_legacy(
        payload: ControlPlaneRouteRequest,
        response: Response,
        request: Request,
    ) -> ControlPlaneRouteResponse:
        _set_deprecation_headers(response)
        routed = _route_control_plane(payload, request)
        _record_usage_metering(tenant_id=routed.tenant_id, dimension="control_plane_route", units=1.0)
        _append_audit_event(
            request,
            action="control_plane.route.evaluate",
            resource_type="control_plane_route",
            resource_id=routed.selected_region,
            details={"operation": routed.operation, "reason": routed.reason},
        )
        return routed

    @app.post(
        f"{API_V1_PREFIX}/control-plane/failover/policies/{{policy_id}}",
        response_model=RegionalFailoverPolicyResponse,
    )
    def upsert_regional_failover_policy_v1(
        policy_id: str,
        payload: RegionalFailoverPolicyUpsertRequest,
        request: Request,
    ) -> RegionalFailoverPolicyResponse:
        policy = _upsert_regional_failover_policy(policy_id, payload)
        _append_audit_event(
            request,
            action="control_plane.failover.policy.upsert",
            resource_type="control_plane_failover_policy",
            resource_id=policy.policy_id,
            details={
                "primary_region": policy.primary_region,
                "secondary_region": policy.secondary_region,
                "write_region": policy.write_region,
                "auto_failback": policy.auto_failback,
            },
        )
        return policy

    @app.post(
        "/control-plane/failover/policies/{policy_id}",
        response_model=RegionalFailoverPolicyResponse,
        deprecated=True,
    )
    def upsert_regional_failover_policy_legacy(
        policy_id: str,
        payload: RegionalFailoverPolicyUpsertRequest,
        response: Response,
        request: Request,
    ) -> RegionalFailoverPolicyResponse:
        _set_deprecation_headers(response)
        policy = _upsert_regional_failover_policy(policy_id, payload)
        _append_audit_event(
            request,
            action="control_plane.failover.policy.upsert",
            resource_type="control_plane_failover_policy",
            resource_id=policy.policy_id,
            details={
                "primary_region": policy.primary_region,
                "secondary_region": policy.secondary_region,
                "write_region": policy.write_region,
                "auto_failback": policy.auto_failback,
            },
        )
        return policy

    @app.get(
        f"{API_V1_PREFIX}/control-plane/failover/policies",
        response_model=RegionalFailoverPolicyListResponse,
    )
    def list_regional_failover_policies_v1() -> RegionalFailoverPolicyListResponse:
        return _list_regional_failover_policies()

    @app.get(
        "/control-plane/failover/policies",
        response_model=RegionalFailoverPolicyListResponse,
        deprecated=True,
    )
    def list_regional_failover_policies_legacy(response: Response) -> RegionalFailoverPolicyListResponse:
        _set_deprecation_headers(response)
        return _list_regional_failover_policies()

    @app.get(
        f"{API_V1_PREFIX}/control-plane/failover/policies/{{policy_id}}",
        response_model=RegionalFailoverPolicyResponse,
    )
    def get_regional_failover_policy_v1(policy_id: str) -> RegionalFailoverPolicyResponse:
        return _get_regional_failover_policy(policy_id)

    @app.get(
        "/control-plane/failover/policies/{policy_id}",
        response_model=RegionalFailoverPolicyResponse,
        deprecated=True,
    )
    def get_regional_failover_policy_legacy(
        policy_id: str,
        response: Response,
    ) -> RegionalFailoverPolicyResponse:
        _set_deprecation_headers(response)
        return _get_regional_failover_policy(policy_id)

    @app.post(
        f"{API_V1_PREFIX}/control-plane/failover/policies/{{policy_id}}/apply",
        response_model=RegionalFailoverApplyResponse,
    )
    def apply_regional_failover_policy_v1(policy_id: str, request: Request) -> RegionalFailoverApplyResponse:
        applied = _apply_regional_failover_policy(policy_id, request)
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="control_plane_failover_apply", units=1.0)
        _append_audit_event(
            request,
            action="control_plane.failover.policy.apply",
            resource_type="control_plane_failover_policy",
            resource_id=policy_id,
            details={"write_region": applied.write_region},
        )
        return applied

    @app.post(
        "/control-plane/failover/policies/{policy_id}/apply",
        response_model=RegionalFailoverApplyResponse,
        deprecated=True,
    )
    def apply_regional_failover_policy_legacy(
        policy_id: str,
        response: Response,
        request: Request,
    ) -> RegionalFailoverApplyResponse:
        _set_deprecation_headers(response)
        applied = _apply_regional_failover_policy(policy_id, request)
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="control_plane_failover_apply", units=1.0)
        _append_audit_event(
            request,
            action="control_plane.failover.policy.apply",
            resource_type="control_plane_failover_policy",
            resource_id=policy_id,
            details={"write_region": applied.write_region},
        )
        return applied

    @app.post(
        f"{API_V1_PREFIX}/control-plane/failover/execute",
        response_model=RegionalFailoverStatusResponse,
    )
    def execute_regional_failover_v1(
        payload: RegionalFailoverExecuteRequest,
        request: Request,
    ) -> RegionalFailoverStatusResponse:
        status = _execute_regional_failover(payload, request)
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="control_plane_failover_execute", units=1.0)
        _append_audit_event(
            request,
            action="control_plane.failover.execute",
            resource_type="control_plane_failover_policy",
            resource_id=payload.policy_id,
            details={"target_region": payload.target_region, "reason": payload.reason},
        )
        return status

    @app.post(
        "/control-plane/failover/execute",
        response_model=RegionalFailoverStatusResponse,
        deprecated=True,
    )
    def execute_regional_failover_legacy(
        payload: RegionalFailoverExecuteRequest,
        response: Response,
        request: Request,
    ) -> RegionalFailoverStatusResponse:
        _set_deprecation_headers(response)
        status = _execute_regional_failover(payload, request)
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="control_plane_failover_execute", units=1.0)
        _append_audit_event(
            request,
            action="control_plane.failover.execute",
            resource_type="control_plane_failover_policy",
            resource_id=payload.policy_id,
            details={"target_region": payload.target_region, "reason": payload.reason},
        )
        return status

    @app.post(
        f"{API_V1_PREFIX}/control-plane/failover/recover",
        response_model=RegionalFailoverStatusResponse,
    )
    def recover_regional_failover_v1(
        payload: RegionalFailoverRecoverRequest,
        request: Request,
    ) -> RegionalFailoverStatusResponse:
        status = _recover_regional_failover(payload, request)
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="control_plane_failover_recover", units=1.0)
        _append_audit_event(
            request,
            action="control_plane.failover.recover",
            resource_type="control_plane_failover_policy",
            resource_id=payload.policy_id,
            details={"reason": payload.reason},
        )
        return status

    @app.post(
        "/control-plane/failover/recover",
        response_model=RegionalFailoverStatusResponse,
        deprecated=True,
    )
    def recover_regional_failover_legacy(
        payload: RegionalFailoverRecoverRequest,
        response: Response,
        request: Request,
    ) -> RegionalFailoverStatusResponse:
        _set_deprecation_headers(response)
        status = _recover_regional_failover(payload, request)
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="control_plane_failover_recover", units=1.0)
        _append_audit_event(
            request,
            action="control_plane.failover.recover",
            resource_type="control_plane_failover_policy",
            resource_id=payload.policy_id,
            details={"reason": payload.reason},
        )
        return status

    @app.get(
        f"{API_V1_PREFIX}/control-plane/failover/status/{{policy_id}}",
        response_model=RegionalFailoverStatusResponse,
    )
    def regional_failover_status_v1(policy_id: str) -> RegionalFailoverStatusResponse:
        return _regional_failover_status(policy_id)

    @app.get(
        "/control-plane/failover/status/{policy_id}",
        response_model=RegionalFailoverStatusResponse,
        deprecated=True,
    )
    def regional_failover_status_legacy(
        policy_id: str,
        response: Response,
    ) -> RegionalFailoverStatusResponse:
        _set_deprecation_headers(response)
        return _regional_failover_status(policy_id)

    @app.post(
        f"{API_V1_PREFIX}/scheduler/cost-aware/models/{{candidate_id}}",
        response_model=CostAwareModelProfileResponse,
    )
    def upsert_cost_aware_model_profile_v1(
        candidate_id: str,
        payload: CostAwareModelProfileUpsertRequest,
        request: Request,
    ) -> CostAwareModelProfileResponse:
        profile = _upsert_cost_aware_model_profile(candidate_id, payload)
        _append_audit_event(
            request,
            action="scheduler.cost_aware.model_profile.upsert",
            resource_type="scheduler_cost_aware_model_profile",
            resource_id=profile.candidate_id,
            details={
                "model_id": profile.model_id,
                "region": profile.region,
            },
        )
        return profile

    @app.post(
        "/scheduler/cost-aware/models/{candidate_id}",
        response_model=CostAwareModelProfileResponse,
        deprecated=True,
    )
    def upsert_cost_aware_model_profile_legacy(
        candidate_id: str,
        payload: CostAwareModelProfileUpsertRequest,
        response: Response,
        request: Request,
    ) -> CostAwareModelProfileResponse:
        _set_deprecation_headers(response)
        profile = _upsert_cost_aware_model_profile(candidate_id, payload)
        _append_audit_event(
            request,
            action="scheduler.cost_aware.model_profile.upsert",
            resource_type="scheduler_cost_aware_model_profile",
            resource_id=profile.candidate_id,
            details={
                "model_id": profile.model_id,
                "region": profile.region,
            },
        )
        return profile

    @app.post(
        f"{API_V1_PREFIX}/scheduler/cost-aware/workers/{{candidate_id}}",
        response_model=CostAwareWorkerProfileResponse,
    )
    def upsert_cost_aware_worker_profile_v1(
        candidate_id: str,
        payload: CostAwareWorkerProfileUpsertRequest,
        request: Request,
    ) -> CostAwareWorkerProfileResponse:
        profile = _upsert_cost_aware_worker_profile(candidate_id, payload)
        _append_audit_event(
            request,
            action="scheduler.cost_aware.worker_profile.upsert",
            resource_type="scheduler_cost_aware_worker_profile",
            resource_id=profile.candidate_id,
            details={
                "worker_pool": profile.worker_pool,
                "region": profile.region,
            },
        )
        return profile

    @app.post(
        "/scheduler/cost-aware/workers/{candidate_id}",
        response_model=CostAwareWorkerProfileResponse,
        deprecated=True,
    )
    def upsert_cost_aware_worker_profile_legacy(
        candidate_id: str,
        payload: CostAwareWorkerProfileUpsertRequest,
        response: Response,
        request: Request,
    ) -> CostAwareWorkerProfileResponse:
        _set_deprecation_headers(response)
        profile = _upsert_cost_aware_worker_profile(candidate_id, payload)
        _append_audit_event(
            request,
            action="scheduler.cost_aware.worker_profile.upsert",
            resource_type="scheduler_cost_aware_worker_profile",
            resource_id=profile.candidate_id,
            details={
                "worker_pool": profile.worker_pool,
                "region": profile.region,
            },
        )
        return profile

    @app.get(
        f"{API_V1_PREFIX}/scheduler/cost-aware/models",
        response_model=CostAwareModelProfileListResponse,
    )
    def list_cost_aware_model_profiles_v1() -> CostAwareModelProfileListResponse:
        return _list_cost_aware_model_profiles()

    @app.get(
        "/scheduler/cost-aware/models",
        response_model=CostAwareModelProfileListResponse,
        deprecated=True,
    )
    def list_cost_aware_model_profiles_legacy(response: Response) -> CostAwareModelProfileListResponse:
        _set_deprecation_headers(response)
        return _list_cost_aware_model_profiles()

    @app.get(
        f"{API_V1_PREFIX}/scheduler/cost-aware/workers",
        response_model=CostAwareWorkerProfileListResponse,
    )
    def list_cost_aware_worker_profiles_v1() -> CostAwareWorkerProfileListResponse:
        return _list_cost_aware_worker_profiles()

    @app.get(
        "/scheduler/cost-aware/workers",
        response_model=CostAwareWorkerProfileListResponse,
        deprecated=True,
    )
    def list_cost_aware_worker_profiles_legacy(response: Response) -> CostAwareWorkerProfileListResponse:
        _set_deprecation_headers(response)
        return _list_cost_aware_worker_profiles()

    @app.post(
        f"{API_V1_PREFIX}/scheduler/cost-aware/route/model",
        response_model=CostAwareScheduleDecisionResponse,
    )
    def route_cost_aware_model_v1(
        payload: CostAwareScheduleRequest,
        request: Request,
    ) -> CostAwareScheduleDecisionResponse:
        decision = _schedule_cost_aware_model(payload, request)
        _record_usage_metering(tenant_id=decision.tenant_id, dimension="cost_aware_route_model", units=1.0)
        _append_audit_event(
            request,
            action="scheduler.cost_aware.model.route",
            resource_type="scheduler_cost_aware_route",
            resource_id=decision.selected_candidate,
            details={"objective": decision.objective, "resource": decision.selected_resource},
        )
        return decision

    @app.post(
        "/scheduler/cost-aware/route/model",
        response_model=CostAwareScheduleDecisionResponse,
        deprecated=True,
    )
    def route_cost_aware_model_legacy(
        payload: CostAwareScheduleRequest,
        response: Response,
        request: Request,
    ) -> CostAwareScheduleDecisionResponse:
        _set_deprecation_headers(response)
        decision = _schedule_cost_aware_model(payload, request)
        _record_usage_metering(tenant_id=decision.tenant_id, dimension="cost_aware_route_model", units=1.0)
        _append_audit_event(
            request,
            action="scheduler.cost_aware.model.route",
            resource_type="scheduler_cost_aware_route",
            resource_id=decision.selected_candidate,
            details={"objective": decision.objective, "resource": decision.selected_resource},
        )
        return decision

    @app.post(
        f"{API_V1_PREFIX}/scheduler/cost-aware/route/worker",
        response_model=CostAwareScheduleDecisionResponse,
    )
    def route_cost_aware_worker_v1(
        payload: CostAwareScheduleRequest,
        request: Request,
    ) -> CostAwareScheduleDecisionResponse:
        decision = _schedule_cost_aware_worker(payload, request)
        _record_usage_metering(tenant_id=decision.tenant_id, dimension="cost_aware_route_worker", units=1.0)
        _append_audit_event(
            request,
            action="scheduler.cost_aware.worker.route",
            resource_type="scheduler_cost_aware_route",
            resource_id=decision.selected_candidate,
            details={"objective": decision.objective, "resource": decision.selected_resource},
        )
        return decision

    @app.post(
        "/scheduler/cost-aware/route/worker",
        response_model=CostAwareScheduleDecisionResponse,
        deprecated=True,
    )
    def route_cost_aware_worker_legacy(
        payload: CostAwareScheduleRequest,
        response: Response,
        request: Request,
    ) -> CostAwareScheduleDecisionResponse:
        _set_deprecation_headers(response)
        decision = _schedule_cost_aware_worker(payload, request)
        _record_usage_metering(tenant_id=decision.tenant_id, dimension="cost_aware_route_worker", units=1.0)
        _append_audit_event(
            request,
            action="scheduler.cost_aware.worker.route",
            resource_type="scheduler_cost_aware_route",
            resource_id=decision.selected_candidate,
            details={"objective": decision.objective, "resource": decision.selected_resource},
        )
        return decision

    @app.post(f"{API_V1_PREFIX}/governance/policies/{{tenant_id}}", response_model=GovernancePolicyResponse)
    def upsert_governance_policy_v1(
        tenant_id: str,
        payload: GovernancePolicyUpsertRequest,
        request: Request,
    ) -> GovernancePolicyResponse:
        policy = _upsert_governance_policy(tenant_id, payload)
        _append_audit_event(
            request,
            action="governance.policy.upsert",
            resource_type="governance_policy",
            resource_id=tenant_id,
            details={
                "consent_required": policy.consent_required,
                "allowed_target_patterns": policy.allowed_target_patterns,
            },
        )
        return policy

    @app.post("/governance/policies/{tenant_id}", response_model=GovernancePolicyResponse, deprecated=True)
    def upsert_governance_policy_legacy(
        tenant_id: str,
        payload: GovernancePolicyUpsertRequest,
        response: Response,
        request: Request,
    ) -> GovernancePolicyResponse:
        _set_deprecation_headers(response)
        policy = _upsert_governance_policy(tenant_id, payload)
        _append_audit_event(
            request,
            action="governance.policy.upsert",
            resource_type="governance_policy",
            resource_id=tenant_id,
            details={
                "consent_required": policy.consent_required,
                "allowed_target_patterns": policy.allowed_target_patterns,
            },
        )
        return policy

    @app.get(f"{API_V1_PREFIX}/governance/policies", response_model=GovernancePolicyListResponse)
    def list_governance_policies_v1() -> GovernancePolicyListResponse:
        return _list_governance_policies()

    @app.get("/governance/policies", response_model=GovernancePolicyListResponse, deprecated=True)
    def list_governance_policies_legacy(response: Response) -> GovernancePolicyListResponse:
        _set_deprecation_headers(response)
        return _list_governance_policies()

    @app.get(f"{API_V1_PREFIX}/governance/policies/{{tenant_id}}", response_model=GovernancePolicyResponse)
    def get_governance_policy_v1(tenant_id: str) -> GovernancePolicyResponse:
        return _get_governance_policy(tenant_id)

    @app.get("/governance/policies/{tenant_id}", response_model=GovernancePolicyResponse, deprecated=True)
    def get_governance_policy_legacy(tenant_id: str, response: Response) -> GovernancePolicyResponse:
        _set_deprecation_headers(response)
        return _get_governance_policy(tenant_id)

    @app.post(f"{API_V1_PREFIX}/governance/evaluate", response_model=GovernanceEvaluationResponse)
    def evaluate_governance_v1(payload: GovernanceEvaluateRequest, request: Request) -> GovernanceEvaluationResponse:
        caller_tenant = _tenant_id(request)
        if payload.tenant_id is not None and payload.tenant_id.strip() and payload.tenant_id.strip() != caller_tenant:
            raise HTTPException(status_code=403, detail="tenant override does not match caller scope")
        target_tenant = payload.tenant_id.strip() if payload.tenant_id is not None else caller_tenant
        if not target_tenant:
            target_tenant = caller_tenant
        evaluation = _evaluate_governance(
            tenant_id=target_tenant,
            action_type=payload.action_type,
            target=payload.target,
            consent_granted=payload.consent_granted,
        )
        _record_usage_metering(tenant_id=target_tenant, dimension="governance_evaluate", units=1.0)
        return evaluation

    @app.post("/governance/evaluate", response_model=GovernanceEvaluationResponse, deprecated=True)
    def evaluate_governance_legacy(
        payload: GovernanceEvaluateRequest,
        response: Response,
        request: Request,
    ) -> GovernanceEvaluationResponse:
        _set_deprecation_headers(response)
        caller_tenant = _tenant_id(request)
        if payload.tenant_id is not None and payload.tenant_id.strip() and payload.tenant_id.strip() != caller_tenant:
            raise HTTPException(status_code=403, detail="tenant override does not match caller scope")
        target_tenant = payload.tenant_id.strip() if payload.tenant_id is not None else caller_tenant
        if not target_tenant:
            target_tenant = caller_tenant
        evaluation = _evaluate_governance(
            tenant_id=target_tenant,
            action_type=payload.action_type,
            target=payload.target,
            consent_granted=payload.consent_granted,
        )
        _record_usage_metering(tenant_id=target_tenant, dimension="governance_evaluate", units=1.0)
        return evaluation

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
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="review_queue_submit", units=1.0)
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
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="review_queue_submit", units=1.0)
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

    @app.post(f"{API_V1_PREFIX}/policy/decisions/evaluate", response_model=PolicyDecisionResponse)
    def evaluate_policy_decision_v1(
        payload: PolicyDecisionEvaluateRequest,
        request: Request,
    ) -> PolicyDecisionResponse:
        decision = _evaluate_policy_decision(payload, tenant_id=_tenant_id(request))
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="policy_decision_evaluate", units=1.0)
        _append_audit_event(
            request,
            action="policy.decision.evaluate",
            resource_type="policy_decision",
            resource_id=decision.decision_id,
            details={
                "allowed": decision.allowed,
                "simulate": decision.simulate,
                "applied_rule_id": decision.applied_rule_id,
            },
        )
        _publish_realtime_event(
            event_type="policy.decision.made",
            tenant_id=_tenant_id(request),
            payload={
                "decision_id": decision.decision_id,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "applied_rule_id": decision.applied_rule_id,
            },
        )
        return decision

    @app.post("/policy/decisions/evaluate", response_model=PolicyDecisionResponse, deprecated=True)
    def evaluate_policy_decision_legacy(
        payload: PolicyDecisionEvaluateRequest,
        response: Response,
        request: Request,
    ) -> PolicyDecisionResponse:
        _set_deprecation_headers(response)
        decision = _evaluate_policy_decision(payload, tenant_id=_tenant_id(request))
        _record_usage_metering(tenant_id=_tenant_id(request), dimension="policy_decision_evaluate", units=1.0)
        _append_audit_event(
            request,
            action="policy.decision.evaluate",
            resource_type="policy_decision",
            resource_id=decision.decision_id,
            details={
                "allowed": decision.allowed,
                "simulate": decision.simulate,
                "applied_rule_id": decision.applied_rule_id,
            },
        )
        _publish_realtime_event(
            event_type="policy.decision.made",
            tenant_id=_tenant_id(request),
            payload={
                "decision_id": decision.decision_id,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "applied_rule_id": decision.applied_rule_id,
            },
        )
        return decision

    @app.get(f"{API_V1_PREFIX}/policy/decisions", response_model=PolicyDecisionListResponse)
    def list_policy_decisions_v1(
        request: Request,
        allowed: bool | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> PolicyDecisionListResponse:
        return _list_policy_decisions(tenant_id=_tenant_id(request), allowed=allowed, limit=limit)

    @app.get("/policy/decisions", response_model=PolicyDecisionListResponse, deprecated=True)
    def list_policy_decisions_legacy(
        response: Response,
        request: Request,
        allowed: bool | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> PolicyDecisionListResponse:
        _set_deprecation_headers(response)
        return _list_policy_decisions(tenant_id=_tenant_id(request), allowed=allowed, limit=limit)

    @app.get(f"{API_V1_PREFIX}/policy/decisions/{{decision_id}}", response_model=PolicyDecisionResponse)
    def get_policy_decision_v1(
        decision_id: str,
        request: Request,
    ) -> PolicyDecisionResponse:
        return _get_policy_decision(decision_id=decision_id, tenant_id=_tenant_id(request))

    @app.get("/policy/decisions/{decision_id}", response_model=PolicyDecisionResponse, deprecated=True)
    def get_policy_decision_legacy(
        decision_id: str,
        response: Response,
        request: Request,
    ) -> PolicyDecisionResponse:
        _set_deprecation_headers(response)
        return _get_policy_decision(decision_id=decision_id, tenant_id=_tenant_id(request))

    @app.get(f"{API_V1_PREFIX}/operator/policy", response_class=HTMLResponse)
    def operator_policy_explorer_v1(
        request: Request,
        allowed: bool | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        decision_id: str | None = Query(default=None),
    ) -> HTMLResponse:
        snapshot = _build_policy_snapshot(
            tenant_id=_tenant_id(request),
            allowed=allowed,
            limit=limit,
            decision_id=decision_id,
        )
        return HTMLResponse(content=_render_policy_explorer(snapshot))

    @app.get("/operator/policy", response_class=HTMLResponse, deprecated=True)
    def operator_policy_explorer_legacy(
        request: Request,
        response: Response,
        allowed: bool | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        decision_id: str | None = Query(default=None),
    ) -> HTMLResponse:
        _set_deprecation_headers(response)
        snapshot = _build_policy_snapshot(
            tenant_id=_tenant_id(request),
            allowed=allowed,
            limit=limit,
            decision_id=decision_id,
        )
        html_response = HTMLResponse(content=_render_policy_explorer(snapshot))
        _set_deprecation_headers(html_response)
        return html_response

    @app.get(f"{API_V1_PREFIX}/operator/policy/snapshot", response_model=PolicyDecisionSnapshotResponse)
    def operator_policy_snapshot_v1(
        request: Request,
        allowed: bool | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        decision_id: str | None = Query(default=None),
    ) -> PolicyDecisionSnapshotResponse:
        return _build_policy_snapshot(
            tenant_id=_tenant_id(request),
            allowed=allowed,
            limit=limit,
            decision_id=decision_id,
        )

    @app.get("/operator/policy/snapshot", response_model=PolicyDecisionSnapshotResponse, deprecated=True)
    def operator_policy_snapshot_legacy(
        request: Request,
        response: Response,
        allowed: bool | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        decision_id: str | None = Query(default=None),
    ) -> PolicyDecisionSnapshotResponse:
        _set_deprecation_headers(response)
        return _build_policy_snapshot(
            tenant_id=_tenant_id(request),
            allowed=allowed,
            limit=limit,
            decision_id=decision_id,
        )

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

    @app.get(f"{API_V1_PREFIX}/monitoring/synthetic")
    def run_synthetic_monitoring_v1(request: Request) -> dict[str, Any]:
        if not synthetic_monitoring_enabled:
            raise HTTPException(status_code=404, detail="synthetic monitoring is disabled")

        report = synthetic_monitor.run_all()
        metrics.record_feature_result(
            "synthetic.monitoring.run",
            success=bool(report.get("overall_healthy", False)),
            trace_id=getattr(request.state, "request_id", None),
            action_type="synthetic_monitoring",
        )
        return report

    @app.get("/monitoring/synthetic", deprecated=True)
    def run_synthetic_monitoring_legacy(response: Response, request: Request) -> dict[str, Any]:
        _set_deprecation_headers(response)
        if not synthetic_monitoring_enabled:
            raise HTTPException(status_code=404, detail="synthetic monitoring is disabled")

        report = synthetic_monitor.run_all()
        metrics.record_feature_result(
            "synthetic.monitoring.run",
            success=bool(report.get("overall_healthy", False)),
            trace_id=getattr(request.state, "request_id", None),
            action_type="synthetic_monitoring",
        )
        return report

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
