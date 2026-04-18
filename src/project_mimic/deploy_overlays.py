"""Helpers for rendering environment-specific deployment overlays."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def load_yaml_dict(path: str) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError(f"yaml must contain a mapping at root: {path}")
    return payload


def render_overlay(base_path: str, overlay_path: str) -> dict[str, Any]:
    base = load_yaml_dict(base_path)
    overlay = load_yaml_dict(overlay_path)
    return deep_merge(base, overlay)
