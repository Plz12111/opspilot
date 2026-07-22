import json
from argparse import Namespace
from pathlib import Path

import pytest
from pydantic import ValidationError

from opspilot.evaluation.cli import run
from opspilot.evaluation.experiment import BaselineComparisonRunner
from opspilot.evaluation.models import EvaluationCase, EvaluationThresholds
from opspilot.evaluation.reporting import render_markdown
from opspilot.evaluation.runner import IncidentEvaluationRunner


def load_cases() -> list[EvaluationCase]:
    raw = json.loads(Path("evals/incidents/cases.json").read_text(encoding="utf-8"))
    return [EvaluationCase.model_validate(item) for item in raw]


async def test_incident_baseline_evaluates_eighty_recorded_cases() -> None:
    cases = load_cases()

    report = await IncidentEvaluationRunner().evaluate(cases)

    assert len(cases) == 80
    assert report.metrics.case_count == 80
    assert report.metrics.top1_accuracy >= 0.60
    assert report.metrics.top3_recall >= 0.80
    assert report.metrics.citation_validity == 1.0
    assert report.metrics.critical_evidence_recall == 1.0
    assert report.metrics.tool_success_rate >= 0.95
    assert report.metrics.prohibited_action_rate == 0.0
    assert report.passed is True
    assert len(report.dataset_digest) == 64


async def test_strict_threshold_keeps_failure_cases_in_report() -> None:
    cases = load_cases()
    runner = IncidentEvaluationRunner(EvaluationThresholds(top1_accuracy=1.0, top3_recall=1.0))

    report = await runner.evaluate(cases)
    markdown = render_markdown(report)

    assert report.passed is False
    assert any(not item.top1_correct for item in report.cases)
    assert "Result: `FAIL`" in markdown
    assert "inventory-latency-telemetry-gap" in markdown


def test_case_rejects_expected_evidence_missing_from_recording() -> None:
    with pytest.raises(ValidationError, match="expected evidence is not recorded"):
        EvaluationCase.model_validate(
            {
                "id": "invalid-case",
                "title": "Invalid fixture",
                "service": "inventory-service",
                "expected_root_cause": "inventory_latency",
                "expected_evidence_ids": ["evd-missing"],
                "observations": [
                    {
                        "id": "evd-present",
                        "tool_name": "query_logs",
                        "source_type": "logs",
                        "content": "recorded observation",
                    }
                ],
            }
        )


async def test_empty_incident_evaluation_suite_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one"):
        await IncidentEvaluationRunner().evaluate([])


async def test_evaluation_cli_writes_json_and_markdown_reports(tmp_path) -> None:
    exit_code = await run(
        Namespace(
            cases=Path("evals/incidents/cases.json"),
            output_dir=tmp_path,
            minimum_cases=80,
            repetitions=2,
        )
    )

    json_report = json.loads((tmp_path / "incident-baseline.json").read_text(encoding="utf-8"))
    markdown_report = (tmp_path / "incident-baseline.md").read_text(encoding="utf-8")
    assert exit_code == 0
    comparison_report = json.loads(
        (tmp_path / "incident-comparison.json").read_text(encoding="utf-8")
    )
    assert json_report["metrics"]["case_count"] == 80
    assert comparison_report["candidate"]["metrics"]["case_count"] == 80
    assert "Top-1 accuracy" in markdown_report


async def test_evaluation_cli_enforces_minimum_case_count(tmp_path) -> None:
    with pytest.raises(ValueError, match="expected at least 81 cases"):
        await run(
            Namespace(
                cases=Path("evals/incidents/cases.json"),
                output_dir=tmp_path,
                minimum_cases=81,
                repetitions=2,
            )
        )


async def test_source_weighted_comparison_improves_top1_and_is_stable() -> None:
    comparison = await BaselineComparisonRunner(repetitions=3).evaluate(load_cases())

    assert comparison.baseline.metrics.case_count == 80
    assert comparison.candidate.metrics.top1_accuracy >= 0.90
    assert comparison.top1_delta >= 0.20
    assert comparison.token_delta == 0
    assert comparison.cost_delta_usd == 0
    assert comparison.stability.top1_agreement == 1.0
    assert comparison.stability.top3_agreement == 1.0


def test_comparison_requires_multiple_repetitions() -> None:
    with pytest.raises(ValueError, match="at least two"):
        BaselineComparisonRunner(repetitions=1)
