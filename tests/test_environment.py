from project_mimic.environment import ProjectMimicEnv
from project_mimic.models import ActionType, UIAction


def test_reset_reinitializes_episode_state() -> None:
    env = ProjectMimicEnv(goal="search flights", max_steps=3)
    obs = env.reset()

    assert obs.step_index == 0
    assert obs.status == "running"
    assert obs.last_event == "reset"
    assert env.state()["history"] == []


def test_step_increments_state_and_returns_reward() -> None:
    env = ProjectMimicEnv(goal="search flights", max_steps=3)
    env.reset()

    action = UIAction(action_type=ActionType.CLICK, target="search-button")
    obs, reward, done, info = env.step(action)

    assert obs.step_index == 1
    assert reward.score > 0
    assert done is False
    assert info["history_length"] == 1


def test_goal_completed_sets_done_true() -> None:
    env = ProjectMimicEnv(goal="search flights", max_steps=5)
    env.reset()

    action = UIAction(
        action_type=ActionType.TYPE,
        text="BOS -> SFO",
        metadata={"goal_completed": True},
    )

    obs, reward, done, _ = env.step(action)
    assert done is True
    assert obs.status == "completed"
    assert reward.score >= 1.0


def test_max_steps_terminates_episode() -> None:
    env = ProjectMimicEnv(goal="search flights", max_steps=2)
    env.reset()

    env.step(UIAction(action_type=ActionType.WAIT, wait_ms=100))
    obs, _, done, _ = env.step(UIAction(action_type=ActionType.WAIT, wait_ms=500))

    assert done is True
    assert obs.status == "max_steps_reached"
