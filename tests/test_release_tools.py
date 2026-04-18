from datetime import date
from pathlib import Path
import subprocess
import sys

import pytest

from project_mimic.release_tools import (
    build_changelog_entry,
    is_valid_semver,
    prepend_changelog,
    replace_pyproject_version,
)


def test_semver_validation() -> None:
    assert is_valid_semver("1.2.3") is True
    assert is_valid_semver("0.1.0-alpha.1") is True
    assert is_valid_semver("1.0") is False


def test_build_changelog_entry_and_prepend() -> None:
    entry = build_changelog_entry(
        "1.2.3",
        ["feat(api): add versioning", "fix(policy): clarify override"],
        today=date(2026, 4, 18),
    )
    assert "## [1.2.3] - 2026-04-18" in entry

    updated = prepend_changelog("# Changelog\n\n## [1.2.2] - 2026-04-10\n", entry)
    assert "[1.2.3]" in updated
    assert updated.index("[1.2.3]") < updated.index("[1.2.2]")


def test_replace_pyproject_version() -> None:
    pyproject = """
[project]
name = "project-mimic"
version = "0.1.0"
""".strip()

    replaced = replace_pyproject_version(pyproject, "0.2.0")
    assert 'version = "0.2.0"' in replaced

    with pytest.raises(ValueError):
        replace_pyproject_version(pyproject, "invalid")


def test_release_script_dry_run(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    changelog_path = tmp_path / "CHANGELOG.md"

    pyproject_path.write_text(
        '[project]\nname = "project-mimic"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    changelog_path.write_text("# Changelog\n\n", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "tools/release/create_release.py",
            "0.2.0",
            "--pyproject",
            str(pyproject_path),
            "--changelog",
            str(changelog_path),
            "--dry-run",
        ],
        check=True,
    )
