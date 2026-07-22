from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from opspilot.agent.graph import DiagnosisSynthesizer, InvestigationRunner
from opspilot.agent.models import InvestigationContext
from opspilot.domain.enums import ToolExecutionStatus
from opspilot.evaluation.baseline import KeywordBaselineSynthesizer
from opspilot.evaluation.models import (
    CaseEvaluationResult,
    EvaluationCase,
    EvaluationMetrics,
    EvaluationReport,
    EvaluationThresholds,
)
from opspilot.evaluation.replay import replay_gateway


class IncidentEvaluationRunner:
    def __init__(
        self,
        thresholds: EvaluationThresholds | None = None,
        synthesizer_factory: Callable[[], DiagnosisSynthesizer] = KeywordBaselineSynthesizer,
        baseline_name: str = "keyword-signature-v1",
    ) -> None:
        self.thresholds = thresholds or EvaluationThresholds()
        self.synthesizer_factory = synthesizer_factory
        self.baseline_name = baseline_name

    async def evaluate(self, cases: list[EvaluationCase]) -> EvaluationReport:
        if not cases:
            raise ValueError("at least one incident evaluation case is required")
        results = [await self._evaluate_case(case) for case in cases]
        metrics = self._aggregate(results)
        thresholds = self.thresholds
        passed = (
            metrics.top1_accuracy >= thresholds.top1_accuracy
            and metrics.top3_recall >= thresholds.top3_recall
            and metrics.citation_validity >= thresholds.citation_validity
            and metrics.tool_success_rate >= thresholds.tool_success_rate
            and metrics.prohibited_action_rate <= thresholds.prohibited_action_rate
        )
        canonical = json.dumps(
            [case.model_dump(mode="json") for case in cases],
            sort_keys=True,
            separators=(",", ":"),
        )
        return EvaluationReport(
            suite_name="incident-agent-baseline-v1",
            baseline_name=self.baseline_name,
            generated_at=datetime.now(UTC),
            dataset_digest=hashlib.sha256(canonical.encode()).hexdigest(),
            metrics=metrics,
            thresholds=thresholds,
            passed=passed,
            cases=results,
        )

    async def _evaluate_case(self, case: EvaluationCase) -> CaseEvaluationResult:
        started = time.perf_counter()
        end_time = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        runner = InvestigationRunner(replay_gateway(case), self.synthesizer_factory())
        result = await runner.run(
            InvestigationContext(
                run_id=f"eval-run-{case.id}",
                incident_id=f"eval-incident-{case.id}",
                service=case.service,
                environment=case.environment,
                start_time=end_time - timedelta(minutes=30),
                end_time=end_time,
                step_budget=case.step_budget,
            )
        )
        predictions = [item.label for item in result.diagnosis.root_causes]
        available_ids = {item.id for item in result.evidence}
        cited_ids = set(result.diagnosis.evidence_ids)
        cited_ids.update(
            evidence_id
            for candidate in result.diagnosis.root_causes
            for evidence_id in candidate.evidence_ids
        )
        valid_citations = cited_ids & available_ids
        expected_ids = set(case.expected_evidence_ids)
        successful_calls = sum(
            item.status == ToolExecutionStatus.SUCCESS for item in result.executions
        )
        prohibited = sorted(set(result.diagnosis.suggested_actions) & set(case.forbidden_actions))
        evidence_chars = sum(len(item.content) for item in result.evidence)
        estimated_tokens = math.ceil(evidence_chars / 4)
        return CaseEvaluationResult(
            case_id=case.id,
            expected_root_cause=case.expected_root_cause,
            predicted_root_causes=predictions,
            top1_correct=bool(predictions and predictions[0] == case.expected_root_cause),
            top3_recalled=case.expected_root_cause in predictions[:3],
            citation_validity=(len(valid_citations) / len(cited_ids) if cited_ids else 0.0),
            critical_evidence_recall=len(expected_ids & cited_ids) / len(expected_ids),
            tool_success_rate=successful_calls / len(result.executions),
            prohibited_actions=prohibited,
            steps_used=result.steps_used,
            latency_ms=int((time.perf_counter() - started) * 1000),
            evidence_chars=evidence_chars,
            estimated_input_tokens=estimated_tokens,
        )

    @staticmethod
    def _aggregate(results: list[CaseEvaluationResult]) -> EvaluationMetrics:
        case_count = len(results)
        latencies = sorted(item.latency_ms for item in results)
        p95_index = max(0, math.ceil(case_count * 0.95) - 1)
        return EvaluationMetrics(
            case_count=case_count,
            top1_accuracy=sum(item.top1_correct for item in results) / case_count,
            top3_recall=sum(item.top3_recalled for item in results) / case_count,
            citation_validity=sum(item.citation_validity for item in results) / case_count,
            critical_evidence_recall=(
                sum(item.critical_evidence_recall for item in results) / case_count
            ),
            tool_success_rate=sum(item.tool_success_rate for item in results) / case_count,
            prohibited_action_rate=(
                sum(bool(item.prohibited_actions) for item in results) / case_count
            ),
            average_steps=sum(item.steps_used for item in results) / case_count,
            p95_latency_ms=latencies[p95_index],
            average_input_tokens=(
                sum(item.estimated_input_tokens for item in results) / case_count
            ),
            estimated_suite_cost_usd=(
                sum(item.estimated_input_tokens for item in results) / 1_000_000 * 0.15
            ),
        )
