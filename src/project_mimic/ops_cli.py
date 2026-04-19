"""Operational CLI for restore, rollback, replay, and quarantine workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

from .queue_runtime import InMemoryActionQueue, JsonFileQueueStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="project-mimic-ops")
    subparsers = parser.add_subparsers(dest="command", required=True)

    restore_parser = subparsers.add_parser("restore", help="Restore a session checkpoint through API")
    _add_api_options(restore_parser)
    restore_parser.add_argument("--session-id", required=True)

    rollback_parser = subparsers.add_parser("rollback", help="Rollback a session to its latest checkpoint")
    _add_api_options(rollback_parser)
    rollback_parser.add_argument("--session-id", required=True)

    replay_parser = subparsers.add_parser("replay", help="Replay a dead-letter queue job")
    _add_queue_options(replay_parser)
    replay_parser.add_argument("--job-id", required=True)

    quarantine_parser = subparsers.add_parser("quarantine", help="Move a queue job to dead-letter")
    _add_queue_options(quarantine_parser)
    quarantine_parser.add_argument("--job-id", required=True)
    quarantine_parser.add_argument("--reason", default="manual quarantine")

    return parser


def _add_api_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)


def _add_queue_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--queue-store", required=True)


def _api_headers(args: argparse.Namespace) -> dict[str, str]:
    headers: dict[str, str] = {}
    api_key = args.api_key.strip() or os.getenv("API_AUTH_KEY", "").strip()
    if api_key:
        headers["X-API-Key"] = api_key
    if args.tenant_id.strip():
        headers["X-Tenant-ID"] = args.tenant_id.strip()
    if args.request_id.strip():
        headers["X-Request-ID"] = args.request_id.strip()
    return headers


def _compose_url(base_url: str, api_prefix: str, path: str) -> str:
    normalized_prefix = api_prefix.strip() or "/api/v1"
    if not normalized_prefix.startswith("/"):
        normalized_prefix = f"/{normalized_prefix}"
    return f"{base_url.rstrip('/')}{normalized_prefix}{path}"


def _run_api_command(
    *,
    method: str,
    operation: str,
    path: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    url = _compose_url(args.base_url, args.api_prefix, path)
    headers = _api_headers(args)

    try:
        response = httpx.request(method, url, headers=headers or None, timeout=args.timeout_seconds)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail: Any
        try:
            detail = exc.response.json()
        except ValueError:
            detail = {"detail": exc.response.text}
        raise RuntimeError(
            f"{operation} failed with status {exc.response.status_code}: {json.dumps(detail, sort_keys=True)}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"{operation} failed to reach API: {exc}") from exc

    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {"raw": response.text}

    return {
        "operation": operation,
        "url": url,
        "result": payload,
    }


def _load_queue(queue_store_path: str) -> InMemoryActionQueue:
    return InMemoryActionQueue(store=JsonFileQueueStore(queue_store_path))


def _run_replay(args: argparse.Namespace) -> dict[str, Any]:
    queue = _load_queue(args.queue_store)
    job = queue.replay_dead_letter(args.job_id)
    return {
        "operation": "replay",
        "queue_store": args.queue_store,
        "job": job.model_dump(mode="json"),
        "queue_depth": queue.queue_depth(),
        "dead_letter_count": len(queue.list_dead_letter()),
    }


def _run_quarantine(args: argparse.Namespace) -> dict[str, Any]:
    queue = _load_queue(args.queue_store)
    job = queue.quarantine(args.job_id, reason=args.reason)
    return {
        "operation": "quarantine",
        "queue_store": args.queue_store,
        "job": job.model_dump(mode="json"),
        "queue_depth": queue.queue_depth(),
        "dead_letter_count": len(queue.list_dead_letter()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "restore":
            payload = _run_api_command(
                method="GET",
                operation="restore",
                path=f"/sessions/{args.session_id}/restore",
                args=args,
            )
        elif args.command == "rollback":
            payload = _run_api_command(
                method="POST",
                operation="rollback",
                path=f"/sessions/{args.session_id}/rollback",
                args=args,
            )
        elif args.command == "replay":
            payload = _run_replay(args)
        elif args.command == "quarantine":
            payload = _run_quarantine(args)
        else:
            raise RuntimeError(f"unsupported command: {args.command}")
    except (KeyError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
