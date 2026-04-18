from project_mimic.orchestrator.state_machine import ActionState, ActionStateMachine, StepSignal


def test_state_machine_reaches_complete_on_happy_path() -> None:
    machine = ActionStateMachine(max_retries=1)

    signals = [
        StepSignal(frame_ready=True),
        StepSignal(intent_confident=True),
        StepSignal(target_resolved=True),
        StepSignal(motion_planned=True),
        StepSignal(events_ack=True),
        StepSignal(verify_ok=True),
    ]

    for signal in signals:
        machine.apply(signal)

    assert machine.state == ActionState.COMPLETE
    assert machine.is_terminal() is True


def test_state_machine_fails_when_retries_exhausted() -> None:
    machine = ActionStateMachine(max_retries=1)

    machine.apply(StepSignal(frame_ready=True))
    machine.apply(StepSignal(intent_confident=False))
    assert machine.state == ActionState.RECOVER

    machine.apply(StepSignal())
    assert machine.state == ActionState.OBSERVE

    machine.apply(StepSignal(frame_ready=True))
    machine.apply(StepSignal(intent_confident=False))
    assert machine.state == ActionState.RECOVER

    machine.apply(StepSignal())
    assert machine.state == ActionState.FAIL
