from datetime import UTC, datetime, timedelta

import pytest

from opspilot.agent.graph import InvestigationRunner
from opspilot.agent.models import Diagnosis, InvestigationContext, RootCauseCandidate
from opspilot.agent.synthesis import (
    CitationValidationError,
    EvidenceGroundedSynthesizer,
)
from tests.fake_tools import fake_observation_gateway


def investigation_context() -> InvestigationContext:
    end = datetime.now(UTC)
    return InvestigationContext(
        run_id="run-citations",
        incident_id="inc-citations",
        service="inventory-service",
        environment="demo",
        start_time=end - timedelta(minutes=10),
        end_time=end,
        step_budget=6,
    )


class InvalidCitationSynthesizer:
    async def synthesize(self, state) -> Diagnosis:
        return Diagnosis(
            summary="Unsupported root cause",
            confidence=0.9,
            evidence_ids=["evd-does-not-exist"],
        )


async def test_graph_rejects_unknown_evidence_citation() -> None:
    runner = InvestigationRunner(fake_observation_gateway(), InvalidCitationSynthesizer())

    with pytest.raises(CitationValidationError, match="unknown evidence IDs"):
        await runner.run(investigation_context())


class InvalidCandidateCitationSynthesizer:
    async def synthesize(self, state) -> Diagnosis:
        return Diagnosis(
            summary="Candidate cites an unavailable source",
            confidence=0.7,
            evidence_ids=[state["evidence"][0]["id"]],
            root_causes=[
                RootCauseCandidate(
                    label="inventory_latency",
                    confidence=0.7,
                    evidence_ids=["evd-candidate-does-not-exist"],
                )
            ],
        )


async def test_graph_rejects_unknown_root_cause_candidate_citation() -> None:
    runner = InvestigationRunner(fake_observation_gateway(), InvalidCandidateCitationSynthesizer())

    with pytest.raises(CitationValidationError, match="unknown evidence IDs"):
        await runner.run(investigation_context())


class RecordingProvider:
    def __init__(self) -> None:
        self.payload = None

    async def generate(self, payload):
        self.payload = payload
        return {
            "summary": "Inventory errors align with the supplied evidence.",
            "confidence": 0.7,
            "evidence_ids": [payload["evidence"][0]["id"]],
            "limitations": [],
        }


async def test_structured_model_synthesizer_only_receives_citable_evidence() -> None:
    provider = RecordingProvider()
    runner = InvestigationRunner(
        fake_observation_gateway(),
        EvidenceGroundedSynthesizer(provider),
    )

    result = await runner.run(investigation_context())

    assert provider.payload is not None
    supplied_ids = {item["id"] for item in provider.payload["evidence"]}
    assert set(result.diagnosis.evidence_ids) <= supplied_ids
    assert result.diagnosis.confidence == 0.7
