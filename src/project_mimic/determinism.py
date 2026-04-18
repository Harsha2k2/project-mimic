"""Deterministic seed helpers shared across planners and benchmark tooling."""

from __future__ import annotations

import os
import random

SEED_ENV_VAR = "PROJECT_MIMIC_SEED"


def set_global_seed(seed: int) -> int:
    random.seed(seed)
    os.environ[SEED_ENV_VAR] = str(seed)
    return seed


def get_global_seed() -> int | None:
    raw = os.getenv(SEED_ENV_VAR)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def resolve_seed(explicit_seed: int | None) -> int | None:
    if explicit_seed is not None:
        return explicit_seed
    return get_global_seed()
