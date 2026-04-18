"""Task catalog and deterministic grader functions for Project Mimic."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskDifficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    title: str
    description: str
    difficulty: TaskDifficulty


@dataclass(frozen=True)
class TaskEvidence:
    search_submitted: bool = False
    offers_extracted: int = 0
    sites_visited: int = 0
    constraints_satisfied: bool = False
    cheapest_selected: bool = False
    steps_used: int = 0
    max_steps: int = 20


def task_catalog() -> list[TaskDefinition]:
    return [
        TaskDefinition(
            task_id="easy.search_submit",
            title="Submit flight search on one site",
            description="Open one travel site, fill required fields, and submit search.",
            difficulty=TaskDifficulty.EASY,
        ),
        TaskDefinition(
            task_id="medium.compare_three_sites",
            title="Compare offers across three sites",
            description="Extract comparable offers from at least three sites and pick lowest price.",
            difficulty=TaskDifficulty.MEDIUM,
        ),
        TaskDefinition(
            task_id="hard.layover_five_sites",
            title="Cheapest valid layover across five sites",
            description=(
                "Find the cheapest flight with approximately one-hour layover across five sites "
                "while respecting constraints."
            ),
            difficulty=TaskDifficulty.HARD,
        ),
    ]


def grade_task(task_id: str, evidence: TaskEvidence) -> float:
    if task_id == "easy.search_submit":
        return _grade_easy(evidence)
    if task_id == "medium.compare_three_sites":
        return _grade_medium(evidence)
    if task_id == "hard.layover_five_sites":
        return _grade_hard(evidence)
    raise ValueError(f"unknown task_id: {task_id}")


def _grade_easy(evidence: TaskEvidence) -> float:
    score = 0.0
    if evidence.search_submitted:
        score += 0.5
    score += min(evidence.offers_extracted, 1) * 0.3
    if evidence.cheapest_selected:
        score += 0.2
    return _clamp(score)


def _grade_medium(evidence: TaskEvidence) -> float:
    score = 0.0
    if evidence.search_submitted:
        score += 0.25
    score += min(evidence.sites_visited, 3) / 3.0 * 0.35
    score += min(evidence.offers_extracted, 6) / 6.0 * 0.25
    if evidence.cheapest_selected:
        score += 0.15
    return _clamp(score)


def _grade_hard(evidence: TaskEvidence) -> float:
    score = 0.0
    if evidence.search_submitted:
        score += 0.20
    score += min(evidence.sites_visited, 5) / 5.0 * 0.20
    score += min(evidence.offers_extracted, 10) / 10.0 * 0.20
    if evidence.constraints_satisfied:
        score += 0.25
    if evidence.cheapest_selected:
        score += 0.15

    # Mild efficiency bonus for reaching outcome with fewer than max steps.
    if evidence.steps_used > 0 and evidence.max_steps > 0:
        efficiency = max(0.0, 1.0 - (evidence.steps_used / evidence.max_steps))
        score += 0.05 * efficiency

    return _clamp(score)


def _clamp(score: float) -> float:
    return max(0.0, min(score, 1.0))
