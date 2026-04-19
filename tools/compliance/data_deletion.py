from __future__ import annotations

import json
from pathlib import Path

import yaml


def _load_json_lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_json_lines(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(item, sort_keys=True) for item in items) + ("\n" if items else ""), encoding="utf-8")


def _prune_mapping(path: Path, session_ids: set[str], tenant_id: str | None) -> tuple[int, int]:
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.read_text(encoding="utf-8").strip() else {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")

    before = len(payload)
    after_payload: dict[str, dict] = {}
    for key, value in payload.items():
        if key in session_ids:
            continue
        if tenant_id:
            record_tenant = str((value or {}).get("tenant_id", ""))
            if record_tenant == tenant_id:
                continue
        after_payload[key] = value

    if after_payload != payload:
        path.write_text(json.dumps(after_payload, sort_keys=True, indent=2), encoding="utf-8")
    return before, len(after_payload)


def _prune_lines(path: Path, session_ids: set[str], tenant_id: str | None) -> tuple[int, int]:
    rows = _load_json_lines(path)
    before = len(rows)
    after_rows = []
    for row in rows:
        row_session_id = str(row.get("session_id", row.get("resource_id", "")))
        row_tenant = str(row.get("tenant_id", ""))
        if row_session_id in session_ids:
            continue
        if tenant_id and row_tenant == tenant_id:
            continue
        after_rows.append(row)

    if after_rows != rows:
        _write_json_lines(path, after_rows)
    return before, len(after_rows)


def main() -> int:
    policy_path = Path(
        __import__("os").getenv("DATA_DELETION_POLICY_PATH", "config/data-deletion.yml")
    )
    if not policy_path.exists():
        print("Data deletion policy missing")
        return 1

    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    session_ids = {str(item) for item in policy.get("session_ids", []) if str(item).strip()}
    tenant_id = str(policy.get("tenant_id", "")).strip() or None
    dry_run = bool(policy.get("dry_run", True))

    if not session_ids and not tenant_id:
        print("No deletion selectors configured")
        return 1

    report: list[dict[str, object]] = []

    metadata_file = str(policy.get("session_metadata_file", "")).strip()
    if metadata_file:
        metadata_path = Path(metadata_file)
        if not metadata_path.exists():
            raise FileNotFoundError(metadata_file)
        before, after = _prune_mapping(metadata_path, session_ids, tenant_id)
        report.append({"target": metadata_file, "before": before, "after": after})

    queue_file = str(policy.get("queue_snapshot_file", "")).strip()
    if queue_file:
        queue_path = Path(queue_file)
        if not queue_path.exists():
            raise FileNotFoundError(queue_file)
        before, after = _prune_mapping(queue_path, session_ids, tenant_id)
        report.append({"target": queue_file, "before": before, "after": after})

    audit_file = str(policy.get("audit_export_file", "")).strip()
    if audit_file:
        audit_path = Path(audit_file)
        if not audit_path.exists():
            raise FileNotFoundError(audit_file)
        before, after = _prune_lines(audit_path, session_ids, tenant_id)
        report.append({"target": audit_file, "before": before, "after": after})

    if dry_run:
        print(json.dumps({"mode": "dry-run", "report": report}, indent=2))
        return 0

    print(json.dumps({"mode": "applied", "report": report}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())