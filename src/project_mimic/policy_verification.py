"""Policy verification tooling for rule-conflict safety."""

from __future__ import annotations

from fnmatch import fnmatchcase
import json
from pathlib import Path
import time
from typing import Any, Protocol
from uuid import uuid4


class PolicyVerificationStore(Protocol):
    def save(self, payload: dict[str, Any]) -> None:
        ...

    def load(self) -> dict[str, Any]:
        ...


class InMemoryPolicyVerificationStore:
    def __init__(self) -> None:
        self._payload: dict[str, Any] = {}

    def save(self, payload: dict[str, Any]) -> None:
        self._payload = json.loads(json.dumps(payload))

    def load(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._payload))


class JsonFilePolicyVerificationStore:
    def __init__(self, file_path: str) -> None:
        if not file_path.strip():
            raise ValueError("file_path must not be empty")
        self._path = Path(file_path)

    def save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}

        content = self._path.read_text(encoding="utf-8").strip()
        if not content:
            return {}

        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            return {}
        return dict(loaded)


class PolicyVerificationService:
    def __init__(self, *, store: PolicyVerificationStore | None = None) -> None:
        self._store = store or InMemoryPolicyVerificationStore()
        payload = self._store.load()
        self._rules: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("rules", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }
        self._reports: dict[str, dict[str, Any]] = {
            str(key): dict(value)
            for key, value in dict(payload.get("reports", {})).items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def upsert_rule(
        self,
        *,
        rule_id: str,
        tenant_id: str,
        effect: str,
        priority: int,
        action_patterns: list[str] | None = None,
        jurisdictions: list[str] | None = None,
        requires_authorization: bool | None = None,
        requires_region_allowed: bool | None = None,
        min_risk_score: float | None = None,
        max_risk_score: float | None = None,
        enabled: bool = True,
        metadata: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized_rule_id = rule_id.strip().lower()
        if not normalized_rule_id:
            raise ValueError("rule_id must not be empty")

        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        normalized_effect = effect.strip().lower()
        if normalized_effect not in {"allow", "deny"}:
            raise ValueError("effect must be one of allow|deny")

        validated_priority = int(priority)
        normalized_action_patterns = self._normalize_patterns(action_patterns or ["*"])
        normalized_jurisdictions = self._normalize_jurisdictions(jurisdictions or ["global"])

        validated_min_risk_score = self._validate_optional_risk_score(min_risk_score, field_name="min_risk_score")
        validated_max_risk_score = self._validate_optional_risk_score(max_risk_score, field_name="max_risk_score")
        if (
            validated_min_risk_score is not None
            and validated_max_risk_score is not None
            and validated_min_risk_score > validated_max_risk_score
        ):
            raise ValueError("min_risk_score must be less than or equal to max_risk_score")

        now = time.time()
        existing = self._rules.get(normalized_rule_id)
        created_at = now if existing is None else float(existing.get("created_at", now))

        payload = {
            "rule_id": normalized_rule_id,
            "tenant_id": normalized_tenant,
            "effect": normalized_effect,
            "priority": validated_priority,
            "action_patterns": normalized_action_patterns,
            "jurisdictions": normalized_jurisdictions,
            "requires_authorization": requires_authorization,
            "requires_region_allowed": requires_region_allowed,
            "min_risk_score": validated_min_risk_score,
            "max_risk_score": validated_max_risk_score,
            "enabled": bool(enabled),
            "metadata": {
                str(key): str(value)
                for key, value in dict(metadata or {}).items()
            },
            "created_at": created_at,
            "updated_at": now,
        }
        self._rules[normalized_rule_id] = payload
        self._persist()
        return dict(payload)

    def get_rule(self, *, rule_id: str, tenant_id: str) -> dict[str, Any]:
        normalized_rule_id = rule_id.strip().lower()
        normalized_tenant = tenant_id.strip()
        if not normalized_rule_id:
            raise ValueError("rule_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        payload = self._rules.get(normalized_rule_id)
        if payload is None:
            raise ValueError("rule not found")
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            raise ValueError("rule does not belong to tenant")
        return dict(payload)

    def list_rules(self, *, tenant_id: str | None = None, include_disabled: bool = True) -> list[dict[str, Any]]:
        normalized_tenant = None if tenant_id is None else tenant_id.strip()
        items: list[dict[str, Any]] = []
        for rule_key in sorted(self._rules.keys()):
            payload = self._rules[rule_key]
            if normalized_tenant and str(payload.get("tenant_id", "")) != normalized_tenant:
                continue
            if not include_disabled and not bool(payload.get("enabled", True)):
                continue
            items.append(dict(payload))
        return items

    def verify(self, *, tenant_id: str, include_disabled: bool = False) -> dict[str, Any]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        all_rules = self.list_rules(tenant_id=normalized_tenant, include_disabled=True)
        candidate_rules = [
            dict(item)
            for item in all_rules
            if include_disabled or bool(item.get("enabled", True))
        ]
        candidate_rules.sort(key=lambda item: (-int(item.get("priority", 0)), str(item.get("rule_id", ""))))

        conflicts: list[dict[str, Any]] = []
        checked_pairs = 0
        for left_index in range(len(candidate_rules)):
            for right_index in range(left_index + 1, len(candidate_rules)):
                checked_pairs += 1
                left_rule = candidate_rules[left_index]
                right_rule = candidate_rules[right_index]
                conflict = self._detect_conflict(left_rule=left_rule, right_rule=right_rule)
                if conflict is not None:
                    conflicts.append(conflict)

        conflict_count = len(conflicts)
        if conflict_count == 0:
            severity = "none"
        elif any(str(item.get("severity", "")).lower() == "high" for item in conflicts):
            severity = "high"
        elif any(str(item.get("severity", "")).lower() == "medium" for item in conflicts):
            severity = "medium"
        else:
            severity = "low"

        report_id = f"pvr_{uuid4().hex[:12]}"
        report = {
            "report_id": report_id,
            "tenant_id": normalized_tenant,
            "include_disabled": bool(include_disabled),
            "total_rules": len(all_rules),
            "active_rules": len([item for item in all_rules if bool(item.get("enabled", True))]),
            "checked_pairs": checked_pairs,
            "conflict_count": conflict_count,
            "severity": severity,
            "conflicts": conflicts,
            "generated_at": time.time(),
        }
        self._reports[report_id] = report
        self._trim_reports(limit=2000)
        self._persist()
        return dict(report)

    def get_report(self, *, report_id: str, tenant_id: str) -> dict[str, Any] | None:
        normalized_report_id = report_id.strip()
        normalized_tenant = tenant_id.strip()
        if not normalized_report_id:
            raise ValueError("report_id must not be empty")
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")

        payload = self._reports.get(normalized_report_id)
        if payload is None:
            return None
        if str(payload.get("tenant_id", "")) != normalized_tenant:
            return None
        return dict(payload)

    def list_reports(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        normalized_tenant = tenant_id.strip()
        if not normalized_tenant:
            raise ValueError("tenant_id must not be empty")
        if limit <= 0:
            return []

        items = [
            dict(item)
            for item in self._reports.values()
            if str(item.get("tenant_id", "")) == normalized_tenant
        ]
        items.sort(key=lambda item: float(item.get("generated_at", 0.0)), reverse=True)
        return items[:limit]

    def _detect_conflict(self, *, left_rule: dict[str, Any], right_rule: dict[str, Any]) -> dict[str, Any] | None:
        if not self._selectors_overlap(left_rule, right_rule):
            return None

        left_rule_id = str(left_rule.get("rule_id", ""))
        right_rule_id = str(right_rule.get("rule_id", ""))
        left_effect = str(left_rule.get("effect", "")).lower()
        right_effect = str(right_rule.get("effect", "")).lower()
        left_priority = int(left_rule.get("priority", 0))
        right_priority = int(right_rule.get("priority", 0))

        if left_effect != right_effect:
            if left_priority == right_priority:
                return {
                    "conflict_id": f"conf_{uuid4().hex[:10]}",
                    "conflict_type": "priority_conflict",
                    "severity": "high",
                    "rule_ids": [left_rule_id, right_rule_id],
                    "summary": "Rules with equal priority have opposing effects on overlapping selectors",
                    "details": {
                        "left_effect": left_effect,
                        "right_effect": right_effect,
                        "priority": left_priority,
                    },
                    "resolution_hint": "Assign unique priorities or narrow selectors to remove ambiguity.",
                }

            return {
                "conflict_id": f"conf_{uuid4().hex[:10]}",
                "conflict_type": "precedence_conflict",
                "severity": "medium",
                "rule_ids": [left_rule_id, right_rule_id],
                "summary": "Overlapping allow and deny rules rely on precedence ordering",
                "details": {
                    "higher_priority_rule": (
                        left_rule_id if left_priority >= right_priority else right_rule_id
                    ),
                    "left_priority": left_priority,
                    "right_priority": right_priority,
                    "left_effect": left_effect,
                    "right_effect": right_effect,
                },
                "resolution_hint": "Document intended precedence or split selectors to avoid accidental policy drift.",
            }

        higher_rule, lower_rule = (
            (left_rule, right_rule)
            if left_priority >= right_priority
            else (right_rule, left_rule)
        )
        if self._is_shadowing(higher_rule=higher_rule, lower_rule=lower_rule):
            return {
                "conflict_id": f"conf_{uuid4().hex[:10]}",
                "conflict_type": "shadowed_rule",
                "severity": "low",
                "rule_ids": [
                    str(higher_rule.get("rule_id", "")),
                    str(lower_rule.get("rule_id", "")),
                ],
                "summary": "Lower-priority rule appears shadowed by broader higher-priority rule with same effect",
                "details": {
                    "higher_priority": int(higher_rule.get("priority", 0)),
                    "lower_priority": int(lower_rule.get("priority", 0)),
                    "effect": str(higher_rule.get("effect", "")),
                },
                "resolution_hint": "Increase specificity or priority of the lower rule if distinct behavior is required.",
            }

        return None

    def _selectors_overlap(self, left_rule: dict[str, Any], right_rule: dict[str, Any]) -> bool:
        left_actions = [str(item) for item in left_rule.get("action_patterns", []) if isinstance(item, str)]
        right_actions = [str(item) for item in right_rule.get("action_patterns", []) if isinstance(item, str)]
        if not any(self._patterns_overlap(left, right) for left in left_actions for right in right_actions):
            return False

        left_jurisdictions = [str(item) for item in left_rule.get("jurisdictions", []) if isinstance(item, str)]
        right_jurisdictions = [str(item) for item in right_rule.get("jurisdictions", []) if isinstance(item, str)]
        if not self._jurisdictions_overlap(left_jurisdictions, right_jurisdictions):
            return False

        left_auth = left_rule.get("requires_authorization")
        right_auth = right_rule.get("requires_authorization")
        if not self._bool_constraint_overlap(left_auth, right_auth):
            return False

        left_region = left_rule.get("requires_region_allowed")
        right_region = right_rule.get("requires_region_allowed")
        if not self._bool_constraint_overlap(left_region, right_region):
            return False

        left_min = self._rule_min_risk(left_rule)
        left_max = self._rule_max_risk(left_rule)
        right_min = self._rule_min_risk(right_rule)
        right_max = self._rule_max_risk(right_rule)
        if max(left_min, right_min) > min(left_max, right_max):
            return False

        return True

    def _is_shadowing(self, *, higher_rule: dict[str, Any], lower_rule: dict[str, Any]) -> bool:
        higher_priority = int(higher_rule.get("priority", 0))
        lower_priority = int(lower_rule.get("priority", 0))
        if higher_priority < lower_priority:
            return False

        higher_actions = [str(item) for item in higher_rule.get("action_patterns", []) if isinstance(item, str)]
        lower_actions = [str(item) for item in lower_rule.get("action_patterns", []) if isinstance(item, str)]
        if not self._pattern_set_contains(container=higher_actions, contained=lower_actions):
            return False

        higher_jurisdictions = [str(item) for item in higher_rule.get("jurisdictions", []) if isinstance(item, str)]
        lower_jurisdictions = [str(item) for item in lower_rule.get("jurisdictions", []) if isinstance(item, str)]
        if not self._jurisdiction_set_contains(container=higher_jurisdictions, contained=lower_jurisdictions):
            return False

        if not self._bool_constraint_contains(
            container=higher_rule.get("requires_authorization"),
            contained=lower_rule.get("requires_authorization"),
        ):
            return False

        if not self._bool_constraint_contains(
            container=higher_rule.get("requires_region_allowed"),
            contained=lower_rule.get("requires_region_allowed"),
        ):
            return False

        higher_min = self._rule_min_risk(higher_rule)
        higher_max = self._rule_max_risk(higher_rule)
        lower_min = self._rule_min_risk(lower_rule)
        lower_max = self._rule_max_risk(lower_rule)
        if not (higher_min <= lower_min and higher_max >= lower_max):
            return False

        return True

    @staticmethod
    def _patterns_overlap(left: str, right: str) -> bool:
        normalized_left = left.strip().lower()
        normalized_right = right.strip().lower()
        if not normalized_left or not normalized_right:
            return False
        if normalized_left == "*" or normalized_right == "*":
            return True
        if normalized_left == normalized_right:
            return True

        left_probe = normalized_left.replace("*", "sample")
        right_probe = normalized_right.replace("*", "sample")
        if fnmatchcase(left_probe, normalized_right):
            return True
        if fnmatchcase(right_probe, normalized_left):
            return True

        left_prefix = normalized_left.split("*", 1)[0]
        right_prefix = normalized_right.split("*", 1)[0]
        if left_prefix and right_prefix:
            return left_prefix.startswith(right_prefix) or right_prefix.startswith(left_prefix)
        return False

    def _pattern_set_contains(self, *, container: list[str], contained: list[str]) -> bool:
        for pattern in contained:
            if not any(self._pattern_contains(outer=outer, inner=pattern) for outer in container):
                return False
        return True

    @staticmethod
    def _pattern_contains(*, outer: str, inner: str) -> bool:
        normalized_outer = outer.strip().lower()
        normalized_inner = inner.strip().lower()
        if normalized_outer == "*":
            return True
        if normalized_outer == normalized_inner:
            return True
        if "*" not in normalized_outer:
            return False

        probe = normalized_inner.replace("*", "sample")
        return fnmatchcase(probe, normalized_outer)

    @staticmethod
    def _jurisdictions_overlap(left: list[str], right: list[str]) -> bool:
        left_set = {item.strip().lower() for item in left if item.strip()}
        right_set = {item.strip().lower() for item in right if item.strip()}
        if not left_set or not right_set:
            return False
        if "global" in left_set or "*" in left_set:
            return True
        if "global" in right_set or "*" in right_set:
            return True
        return bool(left_set.intersection(right_set))

    @staticmethod
    def _jurisdiction_set_contains(*, container: list[str], contained: list[str]) -> bool:
        container_set = {item.strip().lower() for item in container if item.strip()}
        contained_set = {item.strip().lower() for item in contained if item.strip()}
        if not contained_set:
            return True
        if not container_set:
            return False
        if "global" in container_set or "*" in container_set:
            return True
        return contained_set.issubset(container_set)

    @staticmethod
    def _bool_constraint_overlap(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return True
        return bool(left) == bool(right)

    @staticmethod
    def _bool_constraint_contains(*, container: Any, contained: Any) -> bool:
        if container is None:
            return True
        if contained is None:
            return False
        return bool(container) == bool(contained)

    @staticmethod
    def _rule_min_risk(rule: dict[str, Any]) -> float:
        raw = rule.get("min_risk_score")
        return 0.0 if raw is None else float(raw)

    @staticmethod
    def _rule_max_risk(rule: dict[str, Any]) -> float:
        raw = rule.get("max_risk_score")
        return 1.0 if raw is None else float(raw)

    @staticmethod
    def _normalize_patterns(patterns: list[str]) -> list[str]:
        normalized = sorted({item.strip().lower() for item in patterns if item.strip()})
        if not normalized:
            raise ValueError("action_patterns must include at least one pattern")
        return normalized

    @staticmethod
    def _normalize_jurisdictions(jurisdictions: list[str]) -> list[str]:
        normalized = sorted({item.strip().lower() for item in jurisdictions if item.strip()})
        if not normalized:
            raise ValueError("jurisdictions must include at least one value")
        return normalized

    @staticmethod
    def _validate_optional_risk_score(value: float | None, *, field_name: str) -> float | None:
        if value is None:
            return None
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError(f"{field_name} must be between 0.0 and 1.0")
        return numeric

    def _trim_reports(self, *, limit: int) -> None:
        if len(self._reports) <= limit:
            return

        report_ids = sorted(
            self._reports.keys(),
            key=lambda key: float(self._reports[key].get("generated_at", 0.0)),
            reverse=True,
        )
        keep = set(report_ids[:limit])
        self._reports = {
            key: value
            for key, value in self._reports.items()
            if key in keep
        }

    def _persist(self) -> None:
        self._store.save(
            {
                "rules": self._rules,
                "reports": self._reports,
            }
        )
