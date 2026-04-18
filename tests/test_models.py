import pytest

from project_mimic.models import ActionType, UIAction


def test_click_requires_target_or_coordinates() -> None:
    with pytest.raises(ValueError):
        UIAction(action_type=ActionType.CLICK)


def test_type_requires_text() -> None:
    with pytest.raises(ValueError):
        UIAction(action_type=ActionType.TYPE)


def test_valid_click_with_coordinates() -> None:
    action = UIAction(action_type=ActionType.CLICK, x=10, y=20)
    assert action.x == 10
    assert action.y == 20
