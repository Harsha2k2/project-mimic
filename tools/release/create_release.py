#!/usr/bin/env python3
"""Create a semantic version release update and prepend changelog notes."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from project_mimic.release_tools import (
    build_changelog_entry,
    is_valid_semver,
    normalize_commit_summaries,
    prepend_changelog,
    replace_pyproject_version,
)


def _collect_git_commits(limit: int = 30) -> list[str]:
    result = subprocess.run(
        ["git", "--no-pager", "log", f"-n{limit}", "--pretty=format:%s"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return normalize_commit_summaries(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version")
    parser.add_argument("--pyproject", default="pyproject.toml")
    parser.add_argument("--changelog", default="CHANGELOG.md")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not is_valid_semver(args.version):
        raise SystemExit("invalid semantic version")

    pyproject_path = Path(args.pyproject)
    changelog_path = Path(args.changelog)

    commits = _collect_git_commits(limit=30)
    entry = build_changelog_entry(args.version, commits)

    pyproject_updated = replace_pyproject_version(pyproject_path.read_text(encoding="utf-8"), args.version)
    changelog_existing = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else ""
    changelog_updated = prepend_changelog(changelog_existing, entry)

    if args.dry_run:
        print("[dry-run] would update pyproject version and changelog")
        print(entry)
        return 0

    pyproject_path.write_text(pyproject_updated, encoding="utf-8")
    changelog_path.write_text(changelog_updated, encoding="utf-8")
    print(f"release prepared for version {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
