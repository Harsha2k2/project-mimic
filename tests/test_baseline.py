from project_mimic.baseline import deterministic_evidence, parse_evidence, run_baseline


def test_parse_evidence_defaults_and_types() -> None:
    evidence = parse_evidence({"search_submitted": 1, "offers_extracted": "2"})
    assert evidence.search_submitted is True
    assert evidence.offers_extracted == 2
    assert evidence.sites_visited == 0
    assert evidence.max_steps == 20


def test_deterministic_evidence_supports_all_tasks() -> None:
    for task_id in [
        "easy.search_submit",
        "medium.compare_three_sites",
        "hard.layover_five_sites",
    ]:
        evidence = deterministic_evidence(task_id)
        assert evidence.search_submitted is True


def test_run_baseline_deterministic_scores_in_range() -> None:
    results = run_baseline(client=None, model=None)
    assert len(results) == 3
    for result in results:
        assert 0.0 <= result.score <= 1.0
        assert result.source == "deterministic"
