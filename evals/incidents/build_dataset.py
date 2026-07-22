from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

CAUSES = {
    "inventory_dependency_failure": {
        "service": "order-service",
        "phrases": ["inventory returned 503", "connection refused"],
    },
    "inventory_latency": {
        "service": "inventory-service",
        "phrases": ["inventory p95", "deadline exceeded"],
    },
    "database_pool_exhaustion": {
        "service": "inventory-service",
        "phrases": ["connection pool exhausted", "active connections at limit"],
    },
    "redis_cache_stampede": {
        "service": "order-service",
        "phrases": ["cache miss rate", "database qps spike"],
    },
    "bad_deployment": {
        "service": "order-service",
        "phrases": ["error rate after deployment", "new version regression"],
    },
    "memory_leak": {
        "service": "inventory-service",
        "phrases": ["rss grows continuously", "oomkilled"],
    },
    "network_partition": {
        "service": "gateway-service",
        "phrases": ["packet loss", "host unreachable"],
    },
    "certificate_expiry": {
        "service": "gateway-service",
        "phrases": ["certificate expired", "tls handshake failed"],
    },
    "rate_limit_exhaustion": {
        "service": "gateway-service",
        "phrases": ["http 429", "quota exhausted"],
    },
    "disk_saturation": {
        "service": "inventory-service",
        "phrases": ["disk usage above", "no space left"],
    },
}


def observation(
    evidence_id: str,
    tool_name: str,
    source_type: str,
    content: str,
    call_index: int = 1,
) -> dict[str, object]:
    return {
        "id": evidence_id,
        "tool_name": tool_name,
        "source_type": source_type,
        "content": content,
        "call_index": call_index,
    }


def generated_cases() -> list[dict[str, object]]:
    labels = list(CAUSES)
    cases: list[dict[str, object]] = []
    for index, label in enumerate(labels):
        config = CAUSES[label]
        phrases = config["phrases"]
        noise_label = labels[(index + 3) % len(labels)]
        noise_phrases = CAUSES[noise_label]["phrases"]
        prefix = f"g{index + 1:02d}"
        common = {
            "service": config["service"],
            "environment": "demo",
            "expected_root_cause": label,
        }
        cases.extend(
            [
                {
                    **common,
                    "id": f"{label.replace('_', '-')}-corroborated",
                    "title": f"Corroborated {label.replace('_', ' ')} signal",
                    "expected_evidence_ids": [f"evd-{prefix}-c1", f"evd-{prefix}-c2"],
                    "observations": [
                        observation(
                            f"evd-{prefix}-c1",
                            "query_metrics",
                            "metrics",
                            f"runtime metric confirms {phrases[0]}",
                        ),
                        observation(
                            f"evd-{prefix}-c2",
                            "query_logs",
                            "logs",
                            f"application log confirms {phrases[1]}",
                        ),
                    ],
                },
                {
                    **common,
                    "id": f"{label.replace('_', '-')}-single-log",
                    "title": f"Single log signal for {label.replace('_', ' ')}",
                    "expected_evidence_ids": [f"evd-{prefix}-l1"],
                    "observations": [
                        observation(
                            f"evd-{prefix}-l1",
                            "query_logs",
                            "logs",
                            f"runtime failure: {phrases[0]} and {phrases[1]}",
                        )
                    ],
                },
                {
                    **common,
                    "id": f"{label.replace('_', '-')}-runbook-noise",
                    "title": f"Runtime signal with misleading Runbook for {label}",
                    "expected_evidence_ids": [f"evd-{prefix}-n1"],
                    "observations": [
                        observation(
                            f"evd-{prefix}-n1",
                            "query_traces",
                            "traces",
                            f"live trace contains {phrases[0]}",
                        ),
                        observation(
                            f"evd-{prefix}-n2",
                            "search_runbooks",
                            "runbook",
                            f"historical note mentions {noise_phrases[0]} and {noise_phrases[1]}",
                        ),
                    ],
                },
                {
                    **common,
                    "id": f"{label.replace('_', '-')}-telemetry-gap",
                    "title": f"Partial telemetry for {label.replace('_', ' ')}",
                    "expected_evidence_ids": [f"evd-{prefix}-t1"],
                    "failed_tools": ["query_logs"] if index < 5 else [],
                    "observations": [
                        observation(
                            f"evd-{prefix}-t1",
                            "query_traces",
                            "traces",
                            f"surviving trace shows {phrases[0]} and {phrases[1]}",
                        ),
                        observation(
                            f"evd-{prefix}-t2",
                            "query_logs",
                            "logs",
                            "this recording is unavailable when the log tool fails",
                        ),
                    ],
                },
                {
                    **common,
                    "id": f"{label.replace('_', '-')}-ambiguous-noise",
                    "title": f"Ambiguous noisy evidence for {label.replace('_', ' ')}",
                    "expected_evidence_ids": [f"evd-{prefix}-a1"],
                    "observations": [
                        observation(
                            f"evd-{prefix}-a1",
                            "query_metrics",
                            "metrics",
                            f"current incident metric reports {phrases[0]}",
                        ),
                        observation(
                            f"evd-{prefix}-a2",
                            "search_runbooks",
                            "runbook",
                            (
                                "generic recovery text includes "
                                f"{noise_phrases[0]} and {noise_phrases[1]}"
                            ),
                        ),
                    ],
                },
            ]
        )
    return cases


def main() -> None:
    curated = json.loads((ROOT / "cases-v1.json").read_text(encoding="utf-8"))
    cases = [*curated, *generated_cases()]
    if len(cases) != 80:
        raise RuntimeError(f"expected 80 cases, built {len(cases)}")
    (ROOT / "cases.json").write_text(
        json.dumps(cases, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
