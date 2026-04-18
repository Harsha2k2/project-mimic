from project_mimic.mimetic import RustPythonEventBridge, TypoCorrectionStrategy, plan_pointer_stream, synthesize_typing_stream


def test_pointer_replay_is_deterministic_for_same_seed() -> None:
    first = plan_pointer_stream(
        start_x=20.0,
        start_y=40.0,
        target_x=420.0,
        target_y=300.0,
        viewport_width=1280,
        viewport_height=720,
        deterministic_seed=42,
    )
    second = plan_pointer_stream(
        start_x=20.0,
        start_y=40.0,
        target_x=420.0,
        target_y=300.0,
        viewport_width=1280,
        viewport_height=720,
        deterministic_seed=42,
    )

    assert first.events == second.events

    grpc_payload = RustPythonEventBridge.to_grpc_payload(first)
    restored = RustPythonEventBridge.from_rust_events(
        grpc_payload,
        channel="pointer",
        profile=first.profile,
        deterministic_seed=42,
    )
    assert restored.events == first.events


def test_keyboard_replay_is_deterministic_for_same_seed() -> None:
    strategy = TypoCorrectionStrategy(typo_probability=0.2, correction_probability=0.9, max_typos_per_text=2)

    first = synthesize_typing_stream("smart city", strategy=strategy, deterministic_seed=13)
    second = synthesize_typing_stream("smart city", strategy=strategy, deterministic_seed=13)

    assert first.events == second.events
