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
from .observability import InMemoryMetrics
from .policy import PolicyContext, PolicyDecision, PolicyEngine
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
    "InMemoryMetrics",
    "ProjectMimicEnv",
    "ProxyEndpoint",
    "PolicyContext",
    "PolicyDecision",
    "PolicyEngine",
    "ProjectMimicModel",
    "RiskSignals",
    "Reward",
    "TaskDefinition",
    "TaskDifficulty",
    "TaskEvidence",
    "UIAction",
    "calculate_risk_score",
    "grade_task",
    "map_exception_to_error",
    "should_rotate_identity",
    "task_catalog",
]
