from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil
import tarfile
import tempfile

import yaml


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> int:
    manifest_path = Path("config/disaster-recovery.yml")
    if not manifest_path.exists():
        print("No disaster recovery manifest found; skipping check.")
        return 0

    payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    archive_path = Path(str(payload.get("archive_path", "artifacts/disaster-recovery-backup.tar.gz")))
    targets = [Path(item) for item in payload.get("backup_targets", []) or []]

    if not targets:
        print("No disaster recovery targets configured; skipping check.")
        return 0

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as archive:
        for target in targets:
            if not target.exists():
                raise FileNotFoundError(f"missing backup target: {target}")
            archive.add(target, arcname=target.as_posix())

    with tempfile.TemporaryDirectory() as temp_dir:
        restore_root = Path(temp_dir)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(restore_root)

        for target in targets:
            restored = restore_root / target.as_posix()
            if not restored.exists():
                raise FileNotFoundError(f"restored target missing: {target}")
            if target.is_file() and digest(target) != digest(restored):
                raise RuntimeError(f"hash mismatch after restore for {target}")
            if target.is_dir():
                for source_file in target.rglob("*"):
                    if source_file.is_file():
                        restored_file = restore_root / source_file.as_posix()
                        if not restored_file.exists() or digest(source_file) != digest(restored_file):
                            raise RuntimeError(f"hash mismatch after restore for {source_file}")

    shutil.rmtree(archive_path, ignore_errors=False)
    print("Disaster recovery backup/restore validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())