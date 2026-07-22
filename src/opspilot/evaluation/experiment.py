from __future__ import annotations

from opspilot.evaluation.baseline import (
    KeywordBaselineSynthesizer,
    SourceWeightedBaselineSynthesizer,
)
from opspilot.evaluation.models import (
    EvaluationCase,
    EvaluationComparison,
    ExperimentStability,
)
from opspilot.evaluation.runner import IncidentEvaluationRunner


class BaselineComparisonRunner:
    def __init__(self, repetitions: int = 3) -> None:
        if repetitions < 2:
            raise ValueError("comparison requires at least two repetitions")
        self.repetitions = repetitions

    async def evaluate(self, cases: list[EvaluationCase]) -> EvaluationComparison:
        baseline_runner = IncidentEvaluationRunner(
            synthesizer_factory=KeywordBaselineSynthesizer,
            baseline_name="keyword-signature-v1",
        )
        candidate_runner = IncidentEvaluationRunner(
            synthesizer_factory=SourceWeightedBaselineSynthesizer,
            baseline_name="source-weighted-v2",
        )
        baseline = await baseline_runner.evaluate(cases)
        candidate_runs = [await candidate_runner.evaluate(cases) for _ in range(self.repetitions)]
        candidate = candidate_runs[0]
        predictions = [
            {item.case_id: tuple(item.predicted_root_causes[:3]) for item in report.cases}
            for report in candidate_runs
        ]
        top1_stable = 0
        top3_stable = 0
        for case in cases:
            case_predictions = [report[case.id] for report in predictions]
            top1_stable += len({items[:1] for items in case_predictions}) == 1
            top3_stable += len(set(case_predictions)) == 1
        accuracies = [report.metrics.top1_accuracy for report in candidate_runs]
        return EvaluationComparison(
            suite_name="incident-agent-comparison-v2",
            dataset_digest=candidate.dataset_digest,
            baseline=baseline,
            candidate=candidate,
            top1_delta=candidate.metrics.top1_accuracy - baseline.metrics.top1_accuracy,
            top3_delta=candidate.metrics.top3_recall - baseline.metrics.top3_recall,
            token_delta=(
                candidate.metrics.average_input_tokens - baseline.metrics.average_input_tokens
            ),
            cost_delta_usd=(
                candidate.metrics.estimated_suite_cost_usd
                - baseline.metrics.estimated_suite_cost_usd
            ),
            stability=ExperimentStability(
                repetitions=self.repetitions,
                top1_agreement=top1_stable / len(cases),
                top3_agreement=top3_stable / len(cases),
                top1_accuracy_min=min(accuracies),
                top1_accuracy_max=max(accuracies),
            ),
        )
