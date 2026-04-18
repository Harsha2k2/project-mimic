import json

from project_mimic.benchmarking import run_benchmark


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletions:
    def create(self, **_kwargs):
        payload = {
            "search_submitted": True,
            "offers_extracted": 3,
            "sites_visited": 2,
            "constraints_satisfied": True,
            "cheapest_selected": True,
            "steps_used": 10,
            "max_steps": 20,
        }

        class _Response:
            def __init__(self, content: str) -> None:
                self.choices = [_FakeChoice(content)]

        return _Response(json.dumps(payload))


class _FakeChat:
    def __init__(self) -> None:
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self) -> None:
        self.chat = _FakeChat()


def test_benchmark_outputs_per_task_timings_and_history(tmp_path) -> None:
    history = tmp_path / "history.json"
    report = run_benchmark(deterministic_seed=11, history_file=str(history), compare_modes=False)

    assert report.mode == "deterministic"
    assert len(report.task_metrics) == 3
    assert all(item.elapsed_ms >= 0.0 for item in report.task_metrics)
    assert history.exists()

    persisted = json.loads(history.read_text(encoding="utf-8"))
    assert isinstance(persisted, list)
    assert persisted[-1]["deterministic_seed"] == 11


def test_benchmark_reproducibility_tolerance_for_scores(tmp_path) -> None:
    history = tmp_path / "history.json"

    first = run_benchmark(deterministic_seed=17, history_file=str(history), compare_modes=False)
    second = run_benchmark(deterministic_seed=17, history_file=str(history), compare_modes=False)

    first_scores = [item.score for item in first.task_metrics]
    second_scores = [item.score for item in second.task_metrics]
    assert first_scores == second_scores

    first_elapsed = [item.elapsed_ms for item in first.task_metrics]
    second_elapsed = [item.elapsed_ms for item in second.task_metrics]
    for a, b in zip(first_elapsed, second_elapsed):
        assert abs(a - b) < 150.0


def test_benchmark_comparison_report_between_modes(tmp_path) -> None:
    history = tmp_path / "history.json"
    report = run_benchmark(
        client=_FakeClient(),
        model="fake-model",
        deterministic_seed=23,
        history_file=str(history),
        compare_modes=True,
    )

    assert report.comparison["deterministic"] is not None
    assert report.comparison["model"] is not None
    assert report.comparison["delta_by_task"]
    assert report.mode == "openai"
