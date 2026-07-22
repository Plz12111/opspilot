from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.api.dependencies import get_session
from opspilot.integrations.alertmanager.schemas import AlertIngestResult, AlertmanagerWebhook
from opspilot.services.incidents import IncidentService

router = APIRouter(prefix="/api/v1/webhooks", tags=["alertmanager"])


@router.post(
    "/alertmanager", response_model=AlertIngestResult, status_code=status.HTTP_202_ACCEPTED
)
async def receive_alertmanager(
    payload: AlertmanagerWebhook,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertIngestResult:
    result = await IncidentService(session).ingest_alertmanager(payload)
    return AlertIngestResult(
        accepted=result.accepted,
        created=result.created,
        merged=result.merged,
        duplicate_events=result.duplicate_events,
        incident_ids=result.incident_ids or [],
    )
