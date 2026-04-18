import pytest

from project_mimic.tasks import TaskEvidence, grade_task, task_catalog


def test_task_catalog_has_easy_medium_hard() -> None:
    tasks = task_catalog()
    task_ids = {task.task_id for task in tasks}

    assert "easy.search_submit" in task_ids
    assert "medium.compare_three_sites" in task_ids
    assert "hard.layover_five_sites" in task_ids
    assert len(tasks) == 3


def test_easy_grader_rewards_progress() -> None:
    low = grade_task(
        "easy.search_submit",
        TaskEvidence(search_submitted=True, offers_extracted=0, cheapest_selected=False),
    )
    high = grade_task(
        "easy.search_submit",
        TaskEvidence(search_submitted=True, offers_extracted=1, cheapest_selected=True),
    )

    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0
    assert high > low


def test_hard_grader_constraints_and_selection_matter() -> None:
    unconstrained = grade_task(
        "hard.layover_five_sites",
        TaskEvidence(
            search_submitted=True,
            sites_visited=5,
            offers_extracted=10,
            constraints_satisfied=False,
            cheapest_selected=False,
            steps_used=10,
            max_steps=20,
        ),
    )
    constrained = grade_task(
        "hard.layover_five_sites",
        TaskEvidence(
            search_submitted=True,
            sites_visited=5,
            offers_extracted=10,
            constraints_satisfied=True,
            cheapest_selected=True,
            steps_used=10,
            max_steps=20,
        ),
    )

    assert constrained > unconstrained
    assert 0.0 <= constrained <= 1.0


def test_unknown_task_raises_error() -> None:
    with pytest.raises(ValueError):
        grade_task("unknown.task", TaskEvidence())
