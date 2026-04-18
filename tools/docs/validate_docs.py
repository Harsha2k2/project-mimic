#!/usr/bin/env python3
"""Validate required documentation files and basic markdown structure."""

from __future__ import annotations

from pathlib import Path


REQUIRED_DOCS = [
    "docs/project-mimic/README.md",
    "docs/project-mimic/adr/README.md",
    "docs/project-mimic/adr/TEMPLATE.md",
    "docs/project-mimic/ops/04-contributor-quickstart.md",
    "docs/project-mimic/ops/05-troubleshooting.md",
    "docs/project-mimic/lld/06-orchestrator-internals.md",
    "docs/project-mimic/lld/07-vision-internals.md",
]


def _validate_markdown_header(path: Path) -> bool:
    text = path.read_text(encoding="utf-8").lstrip()
    return text.startswith("#")


def main() -> int:
    errors: list[str] = []

    for file_path in REQUIRED_DOCS:
        path = Path(file_path)
        if not path.exists():
            errors.append(f"missing required docs file: {file_path}")
            continue
        if not _validate_markdown_header(path):
            errors.append(f"markdown file missing top-level heading: {file_path}")

    if errors:
        for item in errors:
            print(item)
        return 1

    print("docs validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
