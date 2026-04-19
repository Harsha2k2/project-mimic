import json

import httpx

from project_mimic.ops_cli import main
from project_mimic.queue_runtime import InMemoryActionQueue, JobStatus, JsonFileQueueStore


def test_restore_command_calls_api_and_prints_payload(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_request(method: str, url: str, headers=None, timeout=None):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = dict(headers or {})
        request = httpx.Request(method, url)
        return httpx.Response(200, request=request, json={"state": {"step_index": 1}})

    monkeypatch.setattr("project_mimic.ops_cli.httpx.request", fake_request)

    exit_code = main(
        [
            "restore",
            "--session-id",
            "session-1",
            "--base-url",
            "http://localhost:9000",
            "--api-key",
            "admin-key",
            "--tenant-id",
            "tenant-a",
        ]
    )

    assert exit_code == 0
    assert captured["method"] == "GET"
    assert captured["url"] == "http://localhost:9000/api/v1/sessions/session-1/restore"
    assert captured["headers"] == {"X-API-Key": "admin-key", "X-Tenant-ID": "tenant-a"}

    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "restore"
    assert payload["result"]["state"]["step_index"] == 1


def test_rollback_command_returns_non_zero_on_http_error(monkeypatch, capsys) -> None:
    def fake_request(method: str, url: str, headers=None, timeout=None):
        request = httpx.Request(method, url)
        return httpx.Response(403, request=request, json={"detail": "forbidden"})

    monkeypatch.setattr("project_mimic.ops_cli.httpx.request", fake_request)

    exit_code = main(
        [
            "rollback",
            "--session-id",
            "session-2",
            "--base-url",
            "http://localhost:9000",
        ]
    )

    assert exit_code == 1
    error = capsys.readouterr().err
    assert "rollback failed with status 403" in error


def test_replay_command_requeues_dead_letter_job(tmp_path, capsys) -> None:
    queue_store = tmp_path / "queue-state.json"
    queue = InMemoryActionQueue(store=JsonFileQueueStore(str(queue_store)))

    job = queue.dispatch({"action": "type"}, idempotency_key="replay-1")
    job.max_attempts = 1
    queue.lease_next("worker-a")
    queue.fail("worker-a", job.job_id, reason="fatal")

    exit_code = main(["replay", "--queue-store", str(queue_store), "--job-id", job.job_id])
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "replay"
    assert payload["job"]["status"] == JobStatus.QUEUED.value

    reloaded = InMemoryActionQueue(store=JsonFileQueueStore(str(queue_store)))
    assert reloaded.get_job(job.job_id).status == JobStatus.QUEUED


def test_quarantine_command_moves_job_to_dead_letter(tmp_path, capsys) -> None:
    queue_store = tmp_path / "queue-state.json"
    queue = InMemoryActionQueue(store=JsonFileQueueStore(str(queue_store)))

    job = queue.dispatch({"action": "click"}, idempotency_key="quarantine-1")

    exit_code = main(
        [
            "quarantine",
            "--queue-store",
            str(queue_store),
            "--job-id",
            job.job_id,
            "--reason",
            "suspicious payload",
        ]
    )
    assert exit_code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "quarantine"
    assert payload["job"]["status"] == JobStatus.DEAD_LETTER.value
    assert payload["job"]["last_error"] == "suspicious payload"

    reloaded = InMemoryActionQueue(store=JsonFileQueueStore(str(queue_store)))
    dead = reloaded.list_dead_letter()
    assert len(dead) == 1
    assert dead[0].job_id == job.job_id
