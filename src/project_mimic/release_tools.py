"""Release automation helpers for semantic versioning and changelog generation."""

from __future__ import annotations

from datetime import date
import re

SEMVER_PATTERN = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def is_valid_semver(version: str) -> bool:
    return bool(SEMVER_PATTERN.match(version.strip()))


def normalize_commit_summaries(git_log_output: str) -> list[str]:
    lines = [line.strip() for line in git_log_output.splitlines() if line.strip()]
    return [line.lstrip("- ") for line in lines]


def build_changelog_entry(version: str, commits: list[str], *, today: date | None = None) -> str:
    if not is_valid_semver(version):
        raise ValueError("invalid semantic version")

    changelog_date = (today or date.today()).isoformat()
    header = f"## [{version}] - {changelog_date}"
    body_lines = commits or ["No user-facing changes recorded."]
    bullets = "\n".join(f"- {line}" for line in body_lines)
    return f"{header}\n\n{bullets}\n"


def prepend_changelog(existing_text: str, new_entry: str) -> str:
    stripped = existing_text.strip()
    if not stripped:
        return f"# Changelog\n\n{new_entry}\n"

    if not stripped.startswith("# Changelog"):
        stripped = f"# Changelog\n\n{stripped}"

    marker = "\n\n"
    split_at = stripped.find(marker)
    if split_at == -1:
        return f"{stripped}\n\n{new_entry}\n"

    head = stripped[: split_at + len(marker)]
    tail = stripped[split_at + len(marker) :]
    return f"{head}{new_entry}\n{tail}\n"


def replace_pyproject_version(pyproject_text: str, version: str) -> str:
    if not is_valid_semver(version):
        raise ValueError("invalid semantic version")

    pattern = re.compile(r'(?m)^version\s*=\s*"[^"]+"\s*$')
    replacement = f'version = "{version}"'
    if not pattern.search(pyproject_text):
        raise ValueError("pyproject version field not found")
    return pattern.sub(replacement, pyproject_text, count=1)
