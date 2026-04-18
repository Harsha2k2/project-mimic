"""Baseline task inference and scoring utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .determinism import set_global_seed
from .tasks import TaskEvidence, grade_task, task_catalog


@dataclass(frozen=True)
class BaselineResult:
    task_id: str
    score: float
    evidence: TaskEvidence
    source: str


def build_task_prompt(task_id: str, description: str) -> str:
    return (
        "You are a browser automation planner. "
        "Return JSON only with keys: search_submitted, offers_extracted, sites_visited, "
        "constraints_satisfied, cheapest_selected, steps_used, max_steps. "
        f"Task ID: {task_id}. "
        f"Task: {description}."
    )


def parse_evidence(payload: dict[str, Any]) -> TaskEvidence:
    return TaskEvidence(
        search_submitted=bool(payload.get("search_submitted", False)),
        offers_extracted=int(payload.get("offers_extracted", 0)),
        sites_visited=int(payload.get("sites_visited", 0)),
        constraints_satisfied=bool(payload.get("constraints_satisfied", False)),
        cheapest_selected=bool(payload.get("cheapest_selected", False)),
        steps_used=int(payload.get("steps_used", 0)),
        max_steps=int(payload.get("max_steps", 20)),
    )


def deterministic_evidence(task_id: str) -> TaskEvidence:
    if task_id == "easy.search_submit":
        return TaskEvidence(
            search_submitted=True,
            offers_extracted=1,
            sites_visited=1,
            cheapest_selected=True,
            steps_used=6,
            max_steps=20,
        )
    if task_id == "medium.compare_three_sites":
        return TaskEvidence(
            search_submitted=True,
            offers_extracted=5,
            sites_visited=3,
            cheapest_selected=True,
            steps_used=12,
            max_steps=25,
        )
    if task_id == "hard.layover_five_sites":
        return TaskEvidence(
            search_submitted=True,
            offers_extracted=8,
            sites_visited=5,
            constraints_satisfied=True,
            cheapest_selected=True,
            steps_used=18,
            max_steps=30,
        )
    raise ValueError(f"unknown task_id: {task_id}")


def infer_task_with_openai(client: Any, model: str, task_id: str, description: str) -> TaskEvidence:
    prompt = build_task_prompt(task_id=task_id, description=description)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a precise planning agent."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    content = response.choices[0].message.content or "{}"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = {}
    return parse_evidence(payload)


def run_baseline(
    client: Any | None = None,
    model: str | None = None,
    deterministic_seed: int | None = None,
) -> list[BaselineResult]:
    if deterministic_seed is not None:
        set_global_seed(deterministic_seed)

    results: list[BaselineResult] = []
    for task in task_catalog():
        if client is None or not model:
            evidence = deterministic_evidence(task.task_id)
            source = "deterministic"
        else:
            evidence = infer_task_with_openai(client, model, task.task_id, task.description)
            source = "openai"

        score = grade_task(task.task_id, evidence)
        results.append(BaselineResult(task_id=task.task_id, score=score, evidence=evidence, source=source))
    return results
