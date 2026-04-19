from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


def main() -> int:
    report_path = Path(os.getenv("CANARY_SLO_REPORT_PATH", "artifacts/canary-slo.json"))
    if not report_path.exists():
        print("Canary SLO report missing")
        return 1

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    error_rate = float(payload.get("error_rate", 1.0))
    p95_latency_ms = float(payload.get("p95_latency_ms", 10_000.0))
    min_success_rate = float(payload.get("min_success_rate", 0.98))
    max_p95_latency_ms = float(payload.get("max_p95_latency_ms", 700.0))
    namespace = str(payload.get("canary_namespace", "project-mimic"))
    deployment = str(payload.get("canary_deployment", "mimic-control-plane-canary"))

    success_rate = 1.0 - error_rate
    if success_rate >= min_success_rate and p95_latency_ms <= max_p95_latency_ms:
        print(
            f"Canary healthy: success_rate={success_rate:.4f}, p95_latency_ms={p95_latency_ms:.1f}"
        )
        return 0

    print(
        f"Canary breach detected: success_rate={success_rate:.4f}, p95_latency_ms={p95_latency_ms:.1f}"
    )
    print(f"Rolling back {deployment} in namespace {namespace}")
    if os.getenv("CANARY_ROLLBACK_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}:
        print(f"Dry run: kubectl -n {namespace} scale deployment {deployment} --replicas=0")
    else:
        subprocess.run(
            [
                "kubectl",
                "-n",
                namespace,
                "scale",
                "deployment",
                deployment,
                "--replicas=0",
            ],
            check=True,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())