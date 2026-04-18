import json

import pytest
from pydantic import ValidationError

from project_mimic.error_mapping import map_exception_to_error
from project_mimic.models import ActionType, ErrorCode, Observation, Reward, UIAction


def test_ui_action_roundtrip_json_is_compatible() -> None:
    action = UIAction(action_type=ActionType.CLICK, target="search-btn")
    payload = action.model_dump_json()
    restored = UIAction.model_validate_json(payload)

    assert restored.schema_version == "1.0"
    assert restored.action_type == ActionType.CLICK
    assert restored.target == "search-btn"


def test_observation_and_reward_roundtrip() -> None:
    observation = Observation(step_index=1, goal="g", status="running")
    reward = Reward(score=0.25, reason="partial")

    obs_restored = Observation.model_validate_json(observation.model_dump_json())
    reward_restored = Reward.model_validate_json(reward.model_dump_json())

    assert obs_restored.schema_version == "1.0"
    assert reward_restored.schema_version == "1.0"
    assert reward_restored.score == 0.25


def test_error_mapping_for_validation_and_constraint_errors() -> None:
    with pytest.raises(ValidationError) as exc_info:
        UIAction(action_type=ActionType.TYPE)

    validation_envelope = map_exception_to_error(exc_info.value)
    assert validation_envelope.code == ErrorCode.VALIDATION_ERROR

    constraint_envelope = map_exception_to_error(ValueError("bad constraint"))
    assert constraint_envelope.code == ErrorCode.PAYLOAD_CONSTRAINT_VIOLATION


def test_model_rejects_extra_fields() -> None:
    raw = {
        "schema_version": "1.0",
        "action_type": "wait",
        "wait_ms": 50,
        "metadata": {},
        "unexpected": "value",
    }

    with pytest.raises(ValidationError):
        UIAction.model_validate(raw)


def test_serialized_json_schema_version_stable() -> None:
    action = UIAction(action_type=ActionType.WAIT, wait_ms=10)
    payload = json.loads(action.model_dump_json())
    assert payload["schema_version"] == "1.0"
