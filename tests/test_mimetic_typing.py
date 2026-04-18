from project_mimic.mimetic import TypoCorrectionStrategy, synthesize_typing_stream


def test_typo_strategy_is_bounded() -> None:
    strategy = TypoCorrectionStrategy(typo_probability=9.0, correction_probability=-3.0, max_typos_per_text=-2)

    normalized = strategy.normalized()
    assert normalized.typo_probability == 0.25
    assert normalized.correction_probability == 0.0
    assert normalized.max_typos_per_text == 0


def test_typo_strategy_emits_correction_events_when_forced() -> None:
    strategy = TypoCorrectionStrategy(typo_probability=0.25, correction_probability=1.0, max_typos_per_text=2)

    stream = synthesize_typing_stream("abc", strategy=strategy, deterministic_seed=3)
    backspaces = [event for event in stream.events if event.event_type == "backspace"]

    assert backspaces
    assert all(event.key == "BACKSPACE" for event in backspaces)
