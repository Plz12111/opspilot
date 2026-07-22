from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from opspilot.agent.models import (
    Diagnosis,
    Evidence,
    InvestigationContext,
    InvestigationResult,
    ToolExecution,
    ToolRequest,
)
from opspilot.agent.synthesis import CitationValidator
from opspilot.domain.enums import InvestigationStatus, ToolExecutionStatus
from opspilot.tools.gateway import ToolGateway


class InvestigationState(TypedDict):
    run_id: str
    incident_id: str
    service: str
    environment: str
    start_time: str
    end_time: str
    step_budget: int
    status: str
    plan: list[dict[str, Any]]
    next_step: int
    executions: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    diagnosis: dict[str, Any]


class DiagnosisSynthesizer(Protocol):
    async def synthesize(self, state: InvestigationState) -> Diagnosis: ...


class RuleBasedDiagnosisSynthesizer:
    async def synthesize(self, state: InvestigationState) -> Diagnosis:
        evidence = [Evidence.model_validate(item) for item in state["evidence"]]
        executions = [ToolExecution.model_validate(item) for item in state["executions"]]
        successful_sources = sorted({item.source_type for item in evidence})
        failures = [
            item.request.name for item in executions if item.status != ToolExecutionStatus.SUCCESS
        ]
        limitations: list[str] = []
        if failures:
            limitations.append(f"Unavailable or failed tools: {', '.join(failures)}")
        if not evidence:
            limitations.append("No observability evidence was collected")
        confidence = min(0.35 + len(successful_sources) * 0.15, 0.8) if evidence else 0.1
        summary = (
            f"Collected {len(evidence)} evidence items from "
            f"{', '.join(successful_sources) or 'no available sources'} for "
            f"{state['service']} in {state['environment']}. "
            "This deterministic baseline records evidence but does not claim a root cause."
        )
        return Diagnosis(
            summary=summary,
            confidence=confidence,
            evidence_ids=[item.id for item in evidence],
            limitations=limitations,
        )


class InvestigationRunner:
    def __init__(
        self,
        gateway: ToolGateway,
        synthesizer: DiagnosisSynthesizer | None = None,
        event_sink: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self.gateway = gateway
        self.synthesizer = synthesizer or RuleBasedDiagnosisSynthesizer()
        self.citation_validator = CitationValidator()
        self.event_sink = event_sink
        self.graph = self._build_graph()

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_sink is not None:
            await self.event_sink(event_type, payload)

    async def run(self, context: InvestigationContext) -> InvestigationResult:
        initial: InvestigationState = {
            "run_id": context.run_id,
            "incident_id": context.incident_id,
            "service": context.service,
            "environment": context.environment,
            "start_time": context.start_time.isoformat(),
            "end_time": context.end_time.isoformat(),
            "step_budget": context.step_budget,
            "status": InvestigationStatus.PENDING.value,
            "plan": [],
            "next_step": 0,
            "executions": [],
            "evidence": [],
            "diagnosis": {},
        }
        final = await self.graph.ainvoke(initial)
        return InvestigationResult(
            run_id=final["run_id"],
            incident_id=final["incident_id"],
            status=InvestigationStatus(final["status"]),
            plan=[ToolRequest.model_validate(item) for item in final["plan"]],
            executions=[ToolExecution.model_validate(item) for item in final["executions"]],
            evidence=[Evidence.model_validate(item) for item in final["evidence"]],
            diagnosis=Diagnosis.model_validate(final["diagnosis"]),
            steps_used=len(final["executions"]),
        )

    def _build_graph(self):
        graph = StateGraph(InvestigationState)
        graph.add_node("plan", self._plan)
        graph.add_node("execute", self._execute)
        graph.add_node("synthesize", self._synthesize)
        graph.add_edge(START, "plan")
        graph.add_edge("plan", "execute")
        graph.add_conditional_edges(
            "execute",
            self._next_node,
            {"execute": "execute", "synthesize": "synthesize"},
        )
        graph.add_edge("synthesize", END)
        return graph.compile()

    async def _plan(self, state: InvestigationState) -> dict[str, Any]:
        service = state["service"]
        start = state["start_time"]
        end = state["end_time"]
        plan = [
            ToolRequest(
                name="query_metrics",
                arguments={
                    "query": (
                        "sum(rate(demo_http_requests_total"
                        f'{{service="{service}",status=~"5.."}}[5m]))'
                    ),
                    "start": start,
                    "end": end,
                    "step_seconds": 30,
                },
            ),
            ToolRequest(
                name="query_metrics",
                arguments={
                    "query": (
                        "histogram_quantile(0.95, sum by (le) "
                        "(rate(demo_http_request_duration_seconds_bucket"
                        f'{{service="{service}"}}[5m])))'
                    ),
                    "start": start,
                    "end": end,
                    "step_seconds": 30,
                },
            ),
            ToolRequest(
                name="query_logs",
                arguments={
                    "query": f'{{service_name="{service}"}} |~ "(?i)error|exception|timeout"',
                    "start": start,
                    "end": end,
                    "limit": 100,
                },
            ),
            ToolRequest(
                name="query_traces",
                arguments={"service": service, "start": start, "end": end, "limit": 20},
            ),
            ToolRequest(
                name="search_runbooks",
                arguments={
                    "query": f"{service} error latency timeout troubleshooting recovery",
                    "service": service,
                    "environment": state["environment"],
                    "top_k": 5,
                },
            ),
        ]
        await self._emit(
            "plan.created",
            {
                "steps": [item.model_dump(mode="json") for item in plan],
                "step_budget": state["step_budget"],
            },
        )
        return {
            "plan": [item.model_dump(mode="json") for item in plan],
            "status": InvestigationStatus.RUNNING.value,
        }

    async def _execute(self, state: InvestigationState) -> dict[str, Any]:
        request = ToolRequest.model_validate(state["plan"][state["next_step"]])
        step = state["next_step"] + 1
        await self._emit(
            "tool.started",
            {
                "step": step,
                "tool_name": request.name,
                "arguments": request.arguments,
            },
        )
        execution = await self.gateway.execute(request)
        await self._emit(
            "tool.completed",
            {
                "step": step,
                "tool_call_id": execution.id,
                "tool_name": request.name,
                "status": execution.status.value,
                "latency_ms": execution.latency_ms,
                "error": execution.error,
                "evidence_count": len(execution.evidence),
            },
        )
        new_evidence = [item.model_dump(mode="json") for item in execution.evidence]
        evidence = [*state["evidence"], *new_evidence]
        return {
            "next_step": state["next_step"] + 1,
            "executions": [*state["executions"], execution.model_dump(mode="json")],
            "evidence": evidence,
        }

    @staticmethod
    def _next_node(state: InvestigationState) -> str:
        plan_finished = state["next_step"] >= len(state["plan"])
        budget_exhausted = len(state["executions"]) >= state["step_budget"]
        return "synthesize" if plan_finished or budget_exhausted else "execute"

    async def _synthesize(self, state: InvestigationState) -> dict[str, Any]:
        diagnosis = await self.synthesizer.synthesize(state)
        diagnosis = self.citation_validator.validate(
            diagnosis,
            [Evidence.model_validate(item) for item in state["evidence"]],
        )
        plan_finished = state["next_step"] >= len(state["plan"])
        status = (
            InvestigationStatus.COMPLETED if plan_finished else InvestigationStatus.BUDGET_EXHAUSTED
        )
        await self._emit(
            "synthesis.completed",
            {
                "status": status.value,
                "confidence": diagnosis.confidence,
                "evidence_ids": diagnosis.evidence_ids,
            },
        )
        return {"diagnosis": diagnosis.model_dump(mode="json"), "status": status.value}
