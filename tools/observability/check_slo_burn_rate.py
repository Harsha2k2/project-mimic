from __future__ import annotations

import json
from pathlib import Path

import yaml


def main() -> int:
    policy_path = Path("config/slo-alerts.yml")
    report_path = Path("artifacts/slo-burn-rate.json")

    if not policy_path.exists() or not report_path.exists():
        print("SLO policy or burn-rate report missing")
        return 1

    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    report = json.loads(report_path.read_text(encoding="utf-8"))

    warning = float(policy.get("warning_burn_rate", 1.5))
    paging = float(policy.get("paging_burn_rate", 2.0))
    service_name = str(policy.get("service_name", "project-mimic-api"))
    on_call_target = str(policy.get("on_call_target", "sre-oncall"))
    burn_rate = float(report.get("burn_rate", 0.0))

    if burn_rate < warning:
        print(f"SLO healthy for {service_name}: burn_rate={burn_rate:.2f}")
        return 0

    payload = {
        "service_name": service_name,
        "burn_rate": burn_rate,
        "paging_target": on_call_target,
        "action": "page" if burn_rate >= paging else "warn",
    }
    print(json.dumps(payload, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())