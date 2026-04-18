"""Behavior Tree primitives for high-level orchestration strategy."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable


class NodeStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"


class BehaviorNode(ABC):
    @abstractmethod
    def tick(self, context: dict) -> NodeStatus:
        """Run one node tick against the given context."""


class TaskNode(BehaviorNode):
    def __init__(self, task_fn: Callable[[dict], NodeStatus], name: str | None = None) -> None:
        self._task_fn = task_fn
        self.name = name or task_fn.__name__

    def tick(self, context: dict) -> NodeStatus:
        return self._task_fn(context)


class SequenceNode(BehaviorNode):
    def __init__(self, children: list[BehaviorNode]) -> None:
        self.children = children

    def tick(self, context: dict) -> NodeStatus:
        for child in self.children:
            result = child.tick(context)
            if result == NodeStatus.FAILURE:
                return NodeStatus.FAILURE
            if result == NodeStatus.RUNNING:
                return NodeStatus.RUNNING
        return NodeStatus.SUCCESS


class SelectorNode(BehaviorNode):
    def __init__(self, children: list[BehaviorNode]) -> None:
        self.children = children

    def tick(self, context: dict) -> NodeStatus:
        saw_running = False
        for child in self.children:
            result = child.tick(context)
            if result == NodeStatus.SUCCESS:
                return NodeStatus.SUCCESS
            if result == NodeStatus.RUNNING:
                saw_running = True
        return NodeStatus.RUNNING if saw_running else NodeStatus.FAILURE


class ParallelQuorumNode(BehaviorNode):
    """Runs all children and returns success when quorum succeeds."""

    def __init__(self, children: list[BehaviorNode], min_successes: int) -> None:
        if min_successes <= 0:
            raise ValueError("min_successes must be positive")
        if min_successes > len(children):
            raise ValueError("min_successes cannot exceed child count")

        self.children = children
        self.min_successes = min_successes

    def tick(self, context: dict) -> NodeStatus:
        successes = 0
        failures = 0
        running = 0

        for child in self.children:
            result = child.tick(context)
            if result == NodeStatus.SUCCESS:
                successes += 1
            elif result == NodeStatus.FAILURE:
                failures += 1
            else:
                running += 1

        if successes >= self.min_successes:
            return NodeStatus.SUCCESS

        max_possible_successes = successes + running
        if max_possible_successes < self.min_successes:
            return NodeStatus.FAILURE

        if running > 0:
            return NodeStatus.RUNNING

        return NodeStatus.FAILURE
