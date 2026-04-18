from project_mimic.orchestrator.retry_budget import RetryBudgetManager
from project_mimic.orchestrator.state_machine import ActionState


def test_retry_budget_enforces_state_cap() -> None:
    budget = RetryBudgetManager(per_state_caps={ActionState.RECOVER: 2})

    assert budget.consume(ActionState.RECOVER) is True
    assert budget.consume(ActionState.RECOVER) is True
    assert budget.consume(ActionState.RECOVER) is False


def test_retry_budget_reset_clears_usage() -> None:
    budget = RetryBudgetManager(per_state_caps={ActionState.HYPOTHESIZE: 1})

    assert budget.consume(ActionState.HYPOTHESIZE) is True
    assert budget.consume(ActionState.HYPOTHESIZE) is False

    budget.reset()
    assert budget.consume(ActionState.HYPOTHESIZE) is True
