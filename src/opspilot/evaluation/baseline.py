from __future__ import annotations

from typing import Any

from opspilot.agent.models import (
    Diagnosis,
    Evidence,
    RootCauseCandidate,
    ToolExecution,
)
from opspilot.domain.enums import ToolExecutionStatus

SIGNATURES: dict[str, tuple[str, ...]] = {
    "inventory_dependency_failure": (
        "inventory returned 503",
        "connection refused",
        "upstream inventory failure",
    ),
    "inventory_latency": (
        "inventory p95",
        "deadline exceeded",
        "slow downstream",
    ),
    "database_pool_exhaustion": (
        "connection pool exhausted",
        "timeout acquiring connection",
        "active connections at limit",
    ),
    "redis_cache_stampede": (
        "cache miss rate",
        "redis evictions",
        "database qps spike",
    ),
    "bad_deployment": (
        "error rate after deployment",
        "new version regression",
        "rollback restored",
    ),
    "memory_leak": (
        "rss grows continuously",
        "out of memory",
        "oomkilled",
    ),
    "network_partition": (
        "packet loss",
        "connection reset",
        "host unreachable",
    ),
    "certificate_expiry": (
        "certificate expired",
        "x509",
        "tls handshake failed",
    ),
    "rate_limit_exhaustion": (
        "http 429",
        "rate limit exceeded",
        "quota exhausted",
    ),
    "disk_saturation": (
        "disk usage above",
        "no space left",
        "io wait saturated",
    ),
}

SUGGESTED_ACTIONS = {
    "inventory_dependency_failure": "restart_service",
    "inventory_latency": "restart_service",
    "database_pool_exhaustion": "restart_service",
    "redis_cache_stampede": "restart_service",
    "bad_deployment": "rollback_deployment",
    "memory_leak": "restart_service",
    "network_partition": "escalate_network_team",
    "certificate_expiry": "rotate_certificate",
    "rate_limit_exhaustion": "request_quota_increase",
    "disk_saturation": "expand_demo_volume",
}


class KeywordBaselineSynthesizer:
    """Deterministic, inspectable baseline used to measure future model improvements."""

    async def synthesize(self, state: dict[str, Any]) -> Diagnosis:
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        executions = [ToolExecution.model_validate(item) for item in state["executions"]]
        candidates: list[tuple[int, str, list[str]]] = []
        for label, phrases in SIGNATURES.items():
            matched_ids: list[str] = []
            score = 0
            for item in evidence:
                content = item.content.lower()
                matches = sum(phrase in content for phrase in phrases)
                if matches:
                    score += matches
                    matched_ids.append(item.id)
            if score:
                candidates.append((score, label, list(dict.fromkeys(matched_ids))))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        root_causes = [
            RootCauseCandidate(
                label=label,
                confidence=min(0.45 + score * 0.10, 0.95),
                evidence_ids=evidence_ids,
            )
            for score, label, evidence_ids in candidates[:3]
        ]
        failures = [
            item.request.name for item in executions if item.status != ToolExecutionStatus.SUCCESS
        ]
        limitations = [f"Unavailable tools: {', '.join(failures)}"] if failures else []
        if not root_causes:
            limitations.append("No baseline signature exceeded zero; human review required")
        cited_ids = list(dict.fromkeys(item.id for item in evidence))
        top_label = root_causes[0].label if root_causes else "undetermined"
        confidence = root_causes[0].confidence if root_causes else 0.20
        return Diagnosis(
            summary=f"Keyword baseline ranked {top_label} for {state['service']}.",
            confidence=confidence,
            evidence_ids=cited_ids,
            limitations=limitations,
            root_causes=root_causes,
            suggested_actions=(
                [SUGGESTED_ACTIONS[top_label]] if top_label in SUGGESTED_ACTIONS else []
            ),
        )


class SourceWeightedBaselineSynthesizer:
    """Ranks live telemetry above generic Runbook matches and rewards corroboration."""

    SOURCE_WEIGHTS = {"metrics": 1.25, "logs": 1.15, "traces": 1.20, "runbook": 0.35}

    async def synthesize(self, state: dict[str, Any]) -> Diagnosis:
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        executions = [ToolExecution.model_validate(item) for item in state["executions"]]
        candidates: list[tuple[float, str, list[str]]] = []
        for label, phrases in SIGNATURES.items():
            matched_ids: list[str] = []
            matched_sources: set[str] = set()
            score = 0.0
            for item in evidence:
                content = item.content.lower()
                matches = sum(phrase in content for phrase in phrases)
                if matches:
                    score += matches * self.SOURCE_WEIGHTS.get(item.source_type, 0.5)
                    matched_ids.append(item.id)
                    matched_sources.add(item.source_type)
            if score:
                score += max(0, len(matched_sources) - 1) * 0.30
                candidates.append((score, label, list(dict.fromkeys(matched_ids))))
        candidates.sort(key=lambda item: (-item[0], item[1]))
        root_causes = [
            RootCauseCandidate(
                label=label,
                confidence=min(0.45 + score * 0.08, 0.95),
                evidence_ids=evidence_ids,
            )
            for score, label, evidence_ids in candidates[:3]
        ]
        failures = [
            item.request.name for item in executions if item.status != ToolExecutionStatus.SUCCESS
        ]
        limitations = [f"Unavailable tools: {', '.join(failures)}"] if failures else []
        if not root_causes:
            limitations.append("No weighted signature matched; human review required")
        cited_ids = list(dict.fromkeys(item.id for item in evidence))
        top_label = root_causes[0].label if root_causes else "undetermined"
        return Diagnosis(
            summary=f"Source-weighted baseline ranked {top_label} for {state['service']}.",
            confidence=root_causes[0].confidence if root_causes else 0.20,
            evidence_ids=cited_ids,
            limitations=limitations,
            root_causes=root_causes,
            suggested_actions=(
                [SUGGESTED_ACTIONS[top_label]] if top_label in SUGGESTED_ACTIONS else []
            ),
        )
