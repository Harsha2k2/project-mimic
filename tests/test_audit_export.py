import json
from pathlib import Path

from project_mimic.audit_export import FileAuditExportSink


def test_file_audit_export_sink_writes_jsonl(tmp_path: Path) -> None:
    target = tmp_path / "audit" / "events.jsonl"
    sink = FileAuditExportSink(str(target))

    result = sink.export(
        [
            {"event_id": "e1", "action": "session.create"},
            {"event_id": "e2", "action": "session.step"},
        ]
    )

    assert result["destination"] == "file"
    assert result["exported"] == 2

    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["event_id"] == "e1"
