from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from opspilot.evaluation.models import EvaluationComparison

router = APIRouter(prefix="/api/v1/evaluations", tags=["evaluations"])


@router.get("/latest", response_model=EvaluationComparison)
async def latest_evaluation(request: Request) -> EvaluationComparison:
    report_path = Path(request.app.state.settings.evaluation_report_path)
    if not report_path.is_absolute():
        report_path = Path.cwd() / report_path
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="evaluation report not found; run make eval",
        ) from exc
    return EvaluationComparison.model_validate(payload)
