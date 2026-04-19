# Project Mimic Python SDK

Official Python SDK for integrating with Project Mimic control-plane APIs.

## Usage

```python
from project_mimic_sdk import ProjectMimicClient

with ProjectMimicClient(
    base_url="http://localhost:8000",
    api_key="<api-key>",
    tenant_id="tenant-a",
) as client:
    created = client.create_session(goal="book flight", max_steps=20)
    state = client.session_state(created["session_id"])
```

## Supported Operations

- `create_session`
- `step_session`
- `session_state`
- `list_sessions`
- `restore_session`
- `rollback_session`
- `resume_session`
- `operator_snapshot`
