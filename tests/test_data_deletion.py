from pathlib import Path
from textwrap import dedent

from tools.compliance import data_deletion


def test_data_deletion_dry_run_reports_targets(monkeypatch, tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "data-deletion.yml").write_text(
        dedent(
            """
            session_metadata_file: data/session-metadata.json
            queue_snapshot_file: data/queue.json
            audit_export_file: data/audit.log
            session_ids:
              - sess-1
            tenant_id: tenant-a
            dry_run: true
            """
        ).strip(),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "session-metadata.json").write_text('{"sess-1": {"tenant_id": "tenant-a"}, "sess-2": {"tenant_id": "tenant-b"}}', encoding="utf-8")
    (data_dir / "queue.json").write_text('{"sess-1": {"tenant_id": "tenant-a"}, "sess-3": {"tenant_id": "tenant-c"}}', encoding="utf-8")
    (data_dir / "audit.log").write_text(
        '{"session_id": "sess-1", "tenant_id": "tenant-a"}\n{"session_id": "sess-4", "tenant_id": "tenant-c"}\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert data_deletion.main() == 0


def test_data_deletion_applies_changes(monkeypatch, tmp_path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "data-deletion.yml").write_text(
        dedent(
            """
            session_metadata_file: data/session-metadata.json
            queue_snapshot_file: data/queue.json
            audit_export_file: data/audit.log
            session_ids:
              - sess-1
            tenant_id: ""
            dry_run: false
            """
        ).strip(),
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "session-metadata.json").write_text('{"sess-1": {"tenant_id": "tenant-a"}, "sess-2": {"tenant_id": "tenant-b"}}', encoding="utf-8")
    (data_dir / "queue.json").write_text('{"sess-1": {"tenant_id": "tenant-a"}, "sess-3": {"tenant_id": "tenant-c"}}', encoding="utf-8")
    (data_dir / "audit.log").write_text(
        '{"session_id": "sess-1", "tenant_id": "tenant-a"}\n{"session_id": "sess-4", "tenant_id": "tenant-c"}\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert data_deletion.main() == 0
    assert '"sess-1"' not in (data_dir / "session-metadata.json").read_text(encoding="utf-8")
    assert '"sess-1"' not in (data_dir / "queue.json").read_text(encoding="utf-8")
    assert '"sess-1"' not in (data_dir / "audit.log").read_text(encoding="utf-8")