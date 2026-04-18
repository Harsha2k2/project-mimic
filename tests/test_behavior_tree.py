from project_mimic.orchestrator.behavior_tree import (
    NodeStatus,
    ParallelQuorumNode,
    SelectorNode,
    SequenceNode,
    TaskNode,
)


def test_sequence_fails_on_first_failure() -> None:
    sequence = SequenceNode(
        [
            TaskNode(lambda _: NodeStatus.SUCCESS),
            TaskNode(lambda _: NodeStatus.FAILURE),
            TaskNode(lambda _: NodeStatus.SUCCESS),
        ]
    )

    assert sequence.tick({}) == NodeStatus.FAILURE


def test_selector_returns_success_when_any_child_succeeds() -> None:
    selector = SelectorNode(
        [
            TaskNode(lambda _: NodeStatus.FAILURE),
            TaskNode(lambda _: NodeStatus.SUCCESS),
        ]
    )

    assert selector.tick({}) == NodeStatus.SUCCESS


def test_parallel_quorum_succeeds_at_threshold() -> None:
    quorum = ParallelQuorumNode(
        [
            TaskNode(lambda _: NodeStatus.SUCCESS),
            TaskNode(lambda _: NodeStatus.SUCCESS),
            TaskNode(lambda _: NodeStatus.FAILURE),
        ],
        min_successes=2,
    )

    assert quorum.tick({}) == NodeStatus.SUCCESS
