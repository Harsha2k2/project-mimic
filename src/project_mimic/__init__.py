"""Project Mimic package entrypoint."""

from .environment import ProjectMimicEnv
from .engine import ClickDecision, ExecutionEngine
from .error_mapping import ErrorEnvelope, map_exception_to_error
from .identity import (
    IdentityAllocator,
    IdentityBundle,
    ProxyEndpoint,
    RiskSignals,
    calculate_risk_score,
    should_rotate_identity,
)
from .models import ActionType, ErrorCode, Observation, ProjectMimicModel, Reward, UIAction
from .mimetic import (
    JitterProfile,
    MimeticEvent,
    MimeticEventStream,
    MovementProfile,
    RustPythonEventBridge,
    TypoCorrectionStrategy,
    jitter_profile_for_device,
    movement_profile_for_viewport,
    plan_pointer_stream,
    synthesize_typing_stream,
)
from .observability import InMemoryMetrics
from .policy import PolicyContext, PolicyDecision, PolicyEngine
from .session_lifecycle import (
    InMemoryCheckpointStore,
    InvalidSessionTransitionError,
    RedisCheckpointStore,
    SessionExpiredError,
    SessionRegistry,
    SessionStatus,
)
from .tasks import TaskDefinition, TaskDifficulty, TaskEvidence, grade_task, task_catalog

__all__ = [
    "ActionType",
    "ClickDecision",
    "ErrorCode",
    "ErrorEnvelope",
    "ExecutionEngine",
    "IdentityAllocator",
    "IdentityBundle",
    "Observation",
    "JitterProfile",
    "MimeticEvent",
    "MimeticEventStream",
    "MovementProfile",
    "InMemoryMetrics",
    "InMemoryCheckpointStore",
    "InvalidSessionTransitionError",
    "ProjectMimicEnv",
    "ProxyEndpoint",
    "PolicyContext",
    "PolicyDecision",
    "PolicyEngine",
    "ProjectMimicModel",
    "RiskSignals",
    "RedisCheckpointStore",
    "Reward",
    "RustPythonEventBridge",
    "SessionExpiredError",
    "SessionRegistry",
    "SessionStatus",
    "TaskDefinition",
    "TaskDifficulty",
    "TaskEvidence",
    "TypoCorrectionStrategy",
    "UIAction",
    "calculate_risk_score",
    "grade_task",
    "jitter_profile_for_device",
    "map_exception_to_error",
    "movement_profile_for_viewport",
    "plan_pointer_stream",
    "should_rotate_identity",
    "synthesize_typing_stream",
    "task_catalog",
]
