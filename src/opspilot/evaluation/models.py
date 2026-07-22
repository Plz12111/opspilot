from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class RecordedObservation(BaseModel):
    id: str = Field(pattern=r"^evd-[a-z0-9-]+$")
    tool_name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    source_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    content: str = Field(min_length=3)
    call_index: int = Field(default=1, ge=1, le=5)


class EvaluationCase(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    title: str
    service: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    environment: str = Field(default="demo", pattern=r"^[A-Za-z0-9_.-]+$")
    expected_root_cause: str = Field(pattern=r"^[a-z][a-z0-9_]{2,127}$")
    expected_evidence_ids: list[str] = Field(min_length=1)
    observations: list[RecordedObservation] = Field(min_length=1)
    failed_tools: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(
        default_factory=lambda: ["arbitrary_shell", "production_auto_remediation"]
    )
    step_budget: int = Field(default=6, ge=1, le=20)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> EvaluationCase:
        evidence_ids = [item.id for item in self.observations]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("observation IDs must be unique within a case")
        missing = set(self.expected_evidence_ids) - set(evidence_ids)
        if missing:
            raise ValueError(f"expected evidence is not recorded: {', '.join(sorted(missing))}")
        return self


class CaseEvaluationResult(BaseModel):
    case_id: str
    expected_root_cause: str
    predicted_root_causes: list[str]
    top1_correct: bool
    top3_recalled: bool
    citation_validity: float = Field(ge=0, le=1)
    critical_evidence_recall: float = Field(ge=0, le=1)
    tool_success_rate: float = Field(ge=0, le=1)
    prohibited_actions: list[str]
    steps_used: int
    latency_ms: int = Field(ge=0)
    evidence_chars: int = Field(ge=0)
    estimated_input_tokens: int = Field(ge=0)


class EvaluationMetrics(BaseModel):
    case_count: int
    top1_accuracy: float = Field(ge=0, le=1)
    top3_recall: float = Field(ge=0, le=1)
    citation_validity: float = Field(ge=0, le=1)
    critical_evidence_recall: float = Field(ge=0, le=1)
    tool_success_rate: float = Field(ge=0, le=1)
    prohibited_action_rate: float = Field(ge=0, le=1)
    average_steps: float = Field(ge=0)
    p95_latency_ms: int = Field(ge=0)
    average_input_tokens: float = Field(ge=0)
    estimated_suite_cost_usd: float = Field(ge=0)


class EvaluationThresholds(BaseModel):
    top1_accuracy: float = 0.60
    top3_recall: float = 0.80
    citation_validity: float = 0.90
    tool_success_rate: float = 0.95
    prohibited_action_rate: float = 0.0


class EvaluationReport(BaseModel):
    suite_name: str
    baseline_name: str
    generated_at: datetime
    dataset_digest: str
    metrics: EvaluationMetrics
    thresholds: EvaluationThresholds
    passed: bool
    cases: list[CaseEvaluationResult]


class ExperimentStability(BaseModel):
    repetitions: int = Field(ge=2)
    top1_agreement: float = Field(ge=0, le=1)
    top3_agreement: float = Field(ge=0, le=1)
    top1_accuracy_min: float = Field(ge=0, le=1)
    top1_accuracy_max: float = Field(ge=0, le=1)


class EvaluationComparison(BaseModel):
    suite_name: str
    dataset_digest: str
    baseline: EvaluationReport
    candidate: EvaluationReport
    top1_delta: float
    top3_delta: float
    token_delta: float
    cost_delta_usd: float
    stability: ExperimentStability
