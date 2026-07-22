from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


@dataclass(slots=True)
class Sample:
    status: int
    latency_ms: float
    payload: Any = None
    error: str | None = None


@dataclass(slots=True)
class ScenarioResult:
    name: str
    passed: bool
    requests: int
    duration_seconds: float
    rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    statuses: dict[str, int]
    invariants: dict[str, bool]
    details: dict[str, Any]


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, math.ceil(quantile * len(ordered)) - 1)
    return round(ordered[rank], 2)


def summarize(
    name: str,
    samples: list[Sample],
    duration: float,
    invariants: dict[str, bool],
    details: dict[str, Any] | None = None,
) -> ScenarioResult:
    latencies = [sample.latency_ms for sample in samples]
    statuses = Counter(
        str(sample.status) if sample.status else "transport_error" for sample in samples
    )
    passed = (
        bool(samples) and all(invariants.values()) and not any(sample.error for sample in samples)
    )
    return ScenarioResult(
        name=name,
        passed=passed,
        requests=len(samples),
        duration_seconds=round(duration, 3),
        rps=round(len(samples) / duration, 2) if duration else 0.0,
        p50_ms=percentile(latencies, 0.50),
        p95_ms=percentile(latencies, 0.95),
        p99_ms=percentile(latencies, 0.99),
        statuses=dict(sorted(statuses.items())),
        invariants=invariants,
        details=details or {},
    )


async def request_sample(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> Sample:
    started = time.perf_counter()
    try:
        response = await client.request(method, url, **kwargs)
        try:
            payload: Any = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = response.text[:500]
        return Sample(
            status=response.status_code,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            payload=payload,
        )
    except Exception as exc:
        return Sample(
            status=0,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            error=f"{type(exc).__name__}: {exc}",
        )


async def burst(
    count: int,
    concurrency: int,
    operation: Callable[[int], Awaitable[Sample]],
) -> tuple[list[Sample], float]:
    semaphore = asyncio.Semaphore(concurrency)

    async def limited(index: int) -> Sample:
        async with semaphore:
            return await operation(index)

    started = time.perf_counter()
    samples = await asyncio.gather(*(limited(index) for index in range(count)))
    return samples, time.perf_counter() - started


def alert_payload(run_tag: str, occurrence: int = 0) -> dict[str, Any]:
    starts_at = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=occurrence)
    return {
        "receiver": "opspilot-resilience",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "ResilienceBurst",
                    "service": "order-service",
                    "environment": "demo",
                    "severity": "P1",
                },
                "annotations": {"summary": "Synthetic concurrency validation"},
                "startsAt": starts_at.isoformat().replace("+00:00", "Z"),
                "endsAt": None,
                "generatorURL": "resilience://local",
                "fingerprint": run_tag,
            }
        ],
        "groupLabels": {"alertname": "ResilienceBurst"},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "resilience://local",
        "version": "4",
        "groupKey": f"demo/order-service/{run_tag}",
        "truncatedAlerts": 0,
    }


class ResilienceSuite:
    def __init__(
        self,
        client: httpx.AsyncClient,
        opspilot_url: str,
        gateway_url: str,
        inventory_url: str,
        fault_token: str,
        concurrency: int,
        quick: bool,
    ) -> None:
        self.client = client
        self.opspilot_url = opspilot_url.rstrip("/")
        self.gateway_url = gateway_url.rstrip("/")
        self.inventory_url = inventory_url.rstrip("/")
        self.fault_token = fault_token
        self.concurrency = concurrency
        self.quick = quick
        self.tag = uuid.uuid4().hex[:12]

    async def duplicate_alert_burst(self) -> ScenarioResult:
        count = 20 if self.quick else 50
        payload = alert_payload(f"duplicate-{self.tag}")
        samples, duration = await burst(
            count,
            self.concurrency,
            lambda _: request_sample(
                self.client,
                "POST",
                f"{self.opspilot_url}/api/v1/webhooks/alertmanager",
                json=payload,
            ),
        )
        bodies = [sample.payload for sample in samples if isinstance(sample.payload, dict)]
        incident_ids = {body["incident_ids"][0] for body in bodies if body.get("incident_ids")}
        created = sum(body.get("created", 0) for body in bodies)
        duplicates = sum(body.get("duplicate_events", 0) for body in bodies)
        invariants = {
            "all_requests_accepted": all(sample.status == 202 for sample in samples),
            "one_incident_created": created == 1 and len(incident_ids) == 1,
            "all_retries_deduplicated": duplicates == count - 1,
        }
        return summarize(
            "duplicate_alert_burst",
            samples,
            duration,
            invariants,
            {"created": created, "duplicates": duplicates, "incident_ids": sorted(incident_ids)},
        )

    async def distinct_alert_merge(self) -> ScenarioResult:
        count = 20 if self.quick else 50
        tag = f"merge-{self.tag}"
        samples, duration = await burst(
            count,
            self.concurrency,
            lambda index: request_sample(
                self.client,
                "POST",
                f"{self.opspilot_url}/api/v1/webhooks/alertmanager",
                json=alert_payload(tag, index),
            ),
        )
        bodies = [sample.payload for sample in samples if isinstance(sample.payload, dict)]
        incident_ids = {body["incident_ids"][0] for body in bodies if body.get("incident_ids")}
        incident: dict[str, Any] = {}
        if len(incident_ids) == 1:
            current = await request_sample(
                self.client,
                "GET",
                f"{self.opspilot_url}/api/v1/incidents/{next(iter(incident_ids))}",
            )
            if isinstance(current.payload, dict):
                incident = current.payload
        invariants = {
            "all_requests_accepted": all(sample.status == 202 for sample in samples),
            "occurrences_merged_to_one_incident": len(incident_ids) == 1,
            "alert_count_is_atomic": incident.get("alert_count") == count,
        }
        return summarize(
            "distinct_alert_merge",
            samples,
            duration,
            invariants,
            {
                "incident_ids": sorted(incident_ids),
                "persisted_alert_count": incident.get("alert_count"),
            },
        )

    async def order_idempotency_burst(self) -> ScenarioResult:
        count = 80 if self.quick else 200
        unique_orders = 10 if self.quick else 20

        async def place(index: int) -> Sample:
            order_id = f"resilience-order-{index % unique_orders}"
            return await request_sample(
                self.client,
                "POST",
                f"{self.gateway_url}/api/v1/orders",
                json={"order_id": order_id, "sku": "SKU-001", "quantity": 1},
            )

        samples, duration = await burst(count, self.concurrency, place)
        bodies = [sample.payload for sample in samples if isinstance(sample.payload, dict)]
        order_ids = {body.get("order_id") for body in bodies if body.get("order_id")}
        reservation_ids = {
            body.get("reservation_id") for body in bodies if body.get("reservation_id")
        }
        invariants = {
            "all_orders_succeeded": all(sample.status == 200 for sample in samples),
            "order_ids_are_idempotent": len(order_ids) == unique_orders,
            "inventory_reserved_once_per_order": len(reservation_ids) == unique_orders,
        }
        return summarize(
            "order_idempotency_burst",
            samples,
            duration,
            invariants,
            {"unique_order_ids": len(order_ids), "unique_reservations": len(reservation_ids)},
        )

    async def _create_incident(self, suffix: str) -> str:
        response = await request_sample(
            self.client,
            "POST",
            f"{self.opspilot_url}/api/v1/webhooks/alertmanager",
            json=alert_payload(f"{suffix}-{self.tag}"),
        )
        if response.status != 202 or not isinstance(response.payload, dict):
            raise RuntimeError(f"failed to create incident: {response.error or response.payload}")
        return response.payload["incident_ids"][0]

    async def investigation_idempotency_burst(self) -> ScenarioResult:
        count = 10 if self.quick else 20
        incident_id = await self._create_incident("investigation")
        headers = {"Idempotency-Key": f"investigation-{self.tag}"}
        samples, duration = await burst(
            count,
            min(self.concurrency, count),
            lambda _: request_sample(
                self.client,
                "POST",
                f"{self.opspilot_url}/api/v1/incidents/{incident_id}/investigate",
                headers=headers,
                json={"step_budget": 1},
            ),
        )
        run_ids = {
            sample.payload.get("id")
            for sample in samples
            if isinstance(sample.payload, dict) and sample.payload.get("id")
        }
        terminal: dict[str, Any] = {}
        if len(run_ids) == 1:
            run_id = next(iter(run_ids))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                current = await request_sample(
                    self.client, "GET", f"{self.opspilot_url}/api/v1/runs/{run_id}"
                )
                if isinstance(current.payload, dict):
                    terminal = current.payload
                    if terminal.get("status") not in {"PENDING", "RUNNING"}:
                        break
                await asyncio.sleep(0.2)
        invariants = {
            "all_requests_accepted": all(sample.status == 202 for sample in samples),
            "one_run_created": len(run_ids) == 1,
            "run_reached_terminal_state": terminal.get("status")
            in {"COMPLETED", "BUDGET_EXHAUSTED"},
        }
        return summarize(
            "investigation_idempotency_burst",
            samples,
            duration,
            invariants,
            {"run_ids": sorted(run_ids), "terminal_status": terminal.get("status")},
        )

    async def remediation_exactly_once_burst(self) -> ScenarioResult:
        count = 10 if self.quick else 20
        incident_id = await self._create_incident("remediation")
        proposal = {
            "incident_id": incident_id,
            "action_type": "restart_service",
            "target_environment": "demo",
            "service": "inventory-service",
            "parameters": {"instances": 1},
            "reason": "Validate approval and exactly-once execution under a concurrent burst.",
            "expires_in_minutes": 15,
            "idempotency_key": f"remediation-{self.tag}",
        }
        propose_samples, propose_duration = await burst(
            count,
            min(self.concurrency, count),
            lambda _: request_sample(
                self.client,
                "POST",
                f"{self.opspilot_url}/api/v1/actions",
                headers={"X-Actor-Id": "resilience-investigator"},
                json=proposal,
            ),
        )
        action_ids = {
            sample.payload.get("id")
            for sample in propose_samples
            if isinstance(sample.payload, dict) and sample.payload.get("id")
        }
        approve_samples: list[Sample] = []
        execute_samples: list[Sample] = []
        approve_duration = 0.0
        execute_duration = 0.0
        if len(action_ids) == 1:
            action_id = next(iter(action_ids))
            approve_samples, approve_duration = await burst(
                count,
                min(self.concurrency, count),
                lambda _: request_sample(
                    self.client,
                    "POST",
                    f"{self.opspilot_url}/api/v1/actions/{action_id}/approve",
                    headers={"X-Actor-Id": "demo-approver"},
                    json={"comment": "Concurrent resilience approval."},
                ),
            )
            execute_samples, execute_duration = await burst(
                count,
                min(self.concurrency, count),
                lambda index: request_sample(
                    self.client,
                    "POST",
                    f"{self.opspilot_url}/api/v1/actions/{action_id}/execute",
                    headers={"X-Actor-Id": f"resilience-worker-{index}"},
                ),
            )
        execution_ids = {
            sample.payload.get("execution", {}).get("id")
            for sample in execute_samples
            if isinstance(sample.payload, dict) and sample.payload.get("execution", {}).get("id")
        }
        all_samples = propose_samples + approve_samples + execute_samples
        invariants = {
            "one_action_proposed": len(action_ids) == 1
            and all(sample.status == 201 for sample in propose_samples),
            "approval_is_idempotent": len(approve_samples) == count
            and all(sample.status == 200 for sample in approve_samples),
            "execution_is_exactly_once": len(execution_ids) == 1
            and all(sample.status == 200 for sample in execute_samples),
        }
        return summarize(
            "remediation_exactly_once_burst",
            all_samples,
            propose_duration + approve_duration + execute_duration,
            invariants,
            {"action_ids": sorted(action_ids), "execution_ids": sorted(execution_ids)},
        )

    async def dependency_failure_and_recovery(self) -> ScenarioResult:
        count = 10 if self.quick else 30
        fault_headers = {"X-Fault-Token": self.fault_token}
        configured = await request_sample(
            self.client,
            "PUT",
            f"{self.inventory_url}/internal/faults",
            headers=fault_headers,
            json={"latency_ms": 0, "error_rate": 1.0},
        )
        failure_samples: list[Sample] = []
        recovery_samples: list[Sample] = []
        failure_duration = 0.0
        recovery_duration = 0.0
        try:
            failure_samples, failure_duration = await burst(
                count,
                min(self.concurrency, count),
                lambda index: request_sample(
                    self.client,
                    "POST",
                    f"{self.gateway_url}/api/v1/orders",
                    json={
                        "order_id": f"fault-{self.tag}-{index}",
                        "sku": "SKU-002",
                        "quantity": 1,
                    },
                ),
            )
        finally:
            reset = await request_sample(
                self.client,
                "DELETE",
                f"{self.inventory_url}/internal/faults",
                headers=fault_headers,
            )
        recovery_samples, recovery_duration = await burst(
            5,
            5,
            lambda index: request_sample(
                self.client,
                "POST",
                f"{self.gateway_url}/api/v1/orders",
                json={
                    "order_id": f"resilience-recovery-{index}",
                    "sku": "SKU-002",
                    "quantity": 1,
                },
            ),
        )
        samples = failure_samples + recovery_samples
        invariants = {
            "fault_control_accepted": configured.status == 200,
            "dependency_errors_propagated_as_503": len(failure_samples) == count
            and all(sample.status == 503 for sample in failure_samples),
            "fault_was_reset": reset.status == 204,
            "service_recovered": all(sample.status == 200 for sample in recovery_samples),
        }
        return summarize(
            "dependency_failure_and_recovery",
            samples,
            failure_duration + recovery_duration,
            invariants,
            {"fault_requests": count, "recovery_requests": len(recovery_samples)},
        )


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# OpsPilot resilience report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Run ID: `{report['run_id']}`",
        f"- Result: **{'PASS' if report['passed'] else 'FAIL'}**",
        f"- Requests: **{report['total_requests']}**",
        "",
        "| Scenario | Result | Requests | RPS | P50 | P95 | P99 | Statuses |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for scenario in report["scenarios"]:
        statuses = ", ".join(f"{key}={value}" for key, value in scenario["statuses"].items())
        lines.append(
            f"| `{scenario['name']}` | {'PASS' if scenario['passed'] else 'FAIL'} | "
            f"{scenario['requests']} | {scenario['rps']} | {scenario['p50_ms']} ms | "
            f"{scenario['p95_ms']} ms | {scenario['p99_ms']} ms | {statuses} |"
        )
    lines.extend(["", "## Business invariants", ""])
    for scenario in report["scenarios"]:
        lines.append(f"### `{scenario['name']}`")
        lines.append("")
        for name, passed in scenario["invariants"].items():
            lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
        lines.append("")
    return "\n".join(lines)


def write_reports(report: dict[str, Any], args: argparse.Namespace) -> tuple[Path, Path]:
    json_path = Path(args.json_report)
    markdown_path = Path(args.markdown_report)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    markdown_path.write_text(markdown_report(report) + "\n")
    return json_path, markdown_path


async def run(args: argparse.Namespace) -> int:
    limits = httpx.Limits(
        max_connections=max(args.concurrency * 2, 100),
        max_keepalive_connections=max(args.concurrency, 50),
    )
    timeout = httpx.Timeout(args.timeout)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        suite = ResilienceSuite(
            client=client,
            opspilot_url=args.opspilot_url,
            gateway_url=args.gateway_url,
            inventory_url=args.inventory_url,
            fault_token=args.fault_token,
            concurrency=args.concurrency,
            quick=args.quick,
        )
        health = await request_sample(client, "GET", f"{suite.opspilot_url}/health/ready")
        gateway_health = await request_sample(client, "GET", f"{suite.gateway_url}/health/ready")
        inventory_health = await request_sample(
            client, "GET", f"{suite.inventory_url}/health/ready"
        )
        if any(sample.status != 200 for sample in (health, gateway_health, inventory_health)):
            raise RuntimeError("OpsPilot, gateway and inventory must be ready before the test")
        clean_start = await request_sample(
            client,
            "DELETE",
            f"{suite.inventory_url}/internal/faults",
            headers={"X-Fault-Token": args.fault_token},
        )
        if clean_start.status != 204:
            raise RuntimeError("failed to reset inventory fault state before the test")

        scenario_methods = [
            suite.duplicate_alert_burst,
            suite.distinct_alert_merge,
            suite.order_idempotency_burst,
            suite.investigation_idempotency_burst,
            suite.remediation_exactly_once_burst,
            suite.dependency_failure_and_recovery,
        ]
        results: list[ScenarioResult] = []
        for method in scenario_methods:
            result = await method()
            results.append(result)
            print(
                f"{'PASS' if result.passed else 'FAIL'} {result.name}: "
                f"requests={result.requests} rps={result.rps} p95={result.p95_ms}ms"
            )

    report = {
        "schema_version": 1,
        "run_id": suite.tag,
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": all(result.passed for result in results),
        "total_requests": sum(result.requests for result in results),
        "configuration": {
            "concurrency": args.concurrency,
            "quick": args.quick,
            "timeout_seconds": args.timeout,
            "opspilot_url": args.opspilot_url,
            "gateway_url": args.gateway_url,
            "inventory_url": args.inventory_url,
        },
        "scenarios": [asdict(result) for result in results],
    }
    json_path, markdown_path = write_reports(report, args)
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 0 if report["passed"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OpsPilot concurrency, idempotency and dependency-failure validation"
    )
    parser.add_argument("--opspilot-url", default="http://127.0.0.1:8000")
    parser.add_argument("--gateway-url", default="http://127.0.0.1:8080")
    parser.add_argument("--inventory-url", default="http://127.0.0.1:8082")
    parser.add_argument("--fault-token", default="demo-only")
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--json-report", default="evals/reports/resilience-latest.json")
    parser.add_argument("--markdown-report", default="evals/reports/resilience-latest.md")
    args = parser.parse_args()
    if args.concurrency < 1 or args.concurrency > 500:
        parser.error("--concurrency must be between 1 and 500")
    if args.timeout <= 0 or args.timeout > 120:
        parser.error("--timeout must be between 0 and 120 seconds")
    return args


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
