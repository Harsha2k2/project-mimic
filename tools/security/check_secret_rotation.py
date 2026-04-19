from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sys

import yaml


def parse_iso_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).date()


def main() -> int:
    config_path = Path("config/secret-rotation.yml")
    if not config_path.exists():
        print("No secret rotation policy file found; skipping check.")
        return 0

    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    warning_window_days = int(payload.get("warning_window_days", 14))
    secrets = payload.get("secrets", []) or []

    today = date.today()
    expired: list[str] = []
    expiring_soon: list[str] = []

    for secret in secrets:
        name = str(secret.get("name", "unknown"))
        expires_at = str(secret.get("expires_at", "")).strip()
        if not expires_at:
            print(f"[error] {name}: missing expires_at")
            return 1

        expires_date = parse_iso_date(expires_at)
        days_remaining = (expires_date - today).days
        if days_remaining < 0:
            expired.append(name)
        elif days_remaining <= warning_window_days:
            expiring_soon.append(f"{name} ({days_remaining} days remaining)")

    if expired or expiring_soon:
        if expired:
            print("Expired secrets:")
            for item in expired:
                print(f"- {item}")
        if expiring_soon:
            print("Expiring soon:")
            for item in expiring_soon:
                print(f"- {item}")
        return 1

    print("No secrets are within the rotation warning window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())