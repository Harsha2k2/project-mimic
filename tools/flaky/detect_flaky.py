#!/usr/bin/env python3
"""Detect flaky tests by comparing repeated JUnit XML runs and update quarantine list."""

from __future__ import annotations

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def _read_results(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    root = ET.fromstring(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}

    for testcase in root.findall(".//testcase"):
        classname = testcase.attrib.get("classname", "")
        name = testcase.attrib.get("name", "")
        test_id = f"{classname}::{name}".strip(":")
        failed = testcase.find("failure") is not None or testcase.find("error") is not None
        out[test_id] = "failed" if failed else "passed"

    return out


def detect_flaky(first: dict[str, str], second: dict[str, str]) -> list[str]:
    flaky: list[str] = []
    for test_id in sorted(set(first) | set(second)):
        one = first.get(test_id)
        two = second.get(test_id)
        if one is None or two is None:
            continue
        if one != two:
            flaky.append(test_id)
    return flaky


def write_quarantine(path: Path, flaky: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(flaky) + ("\n" if flaky else "")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("first")
    parser.add_argument("second")
    parser.add_argument("output")
    args = parser.parse_args()

    first = _read_results(Path(args.first))
    second = _read_results(Path(args.second))
    flaky = detect_flaky(first, second)
    write_quarantine(Path(args.output), flaky)

    print(f"detected flaky tests: {len(flaky)}")
    for item in flaky:
        print(item)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
