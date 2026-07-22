from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.api.dependencies import get_session
from opspilot.config import Settings
from opspilot.domain.enums import ApprovalDecision
from opspilot.integrations.feishu.events import extract_card_action, store_event
from opspilot.integrations.feishu.security import FeishuRequestVerifier, FeishuSecurityError
from opspilot.remediation.service import (
    RemediationConflictError,
    RemediationNotFoundError,
    RemediationService,
)

router = APIRouter(prefix="/api/v1/integrations/feishu", tags=["feishu"])


def verifier_from(request: Request) -> FeishuRequestVerifier:
    settings: Settings = request.app.state.settings
    return FeishuRequestVerifier(
        verification_token=settings.feishu_verification_token,
        encrypt_key=settings.feishu_encrypt_key,
        max_age_seconds=settings.feishu_callback_max_age_seconds,
    )


async def decode_request(request: Request) -> dict:
    raw_body = await request.body()
    verifier = verifier_from(request)
    try:
        verifier.verify_signature(
            raw_body,
            request.headers.get("X-Lark-Request-Timestamp"),
            request.headers.get("X-Lark-Request-Nonce"),
            request.headers.get("X-Lark-Signature"),
        )
        body = verifier.decode_body(raw_body)
        verifier.verify_token(body)
        return body
    except FeishuSecurityError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


async def handle_callback(request: Request, session: AsyncSession) -> dict[str, str | int | bool]:
    body = await decode_request(request)
    if body.get("type") == "url_verification":
        return {"challenge": str(body.get("challenge", ""))}
    stored = await store_event(session, body)
    return {"code": 0, "duplicate": stored.duplicate}


@router.post("/events")
async def receive_event(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict[str, str | int | bool]:
    return await handle_callback(request, session)


@router.post("/card-actions")
async def receive_card_action(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> dict[str, str | int | bool]:
    body = await decode_request(request)
    if body.get("type") == "url_verification":
        return {"challenge": str(body.get("challenge", ""))}
    stored = await store_event(session, body)
    card_action = extract_card_action(body)
    if card_action is None:
        return {"code": 0, "duplicate": stored.duplicate}
    decisions = {
        "remediation.approve": ApprovalDecision.APPROVED,
        "remediation.reject": ApprovalDecision.REJECTED,
    }
    decision = decisions.get(card_action.action)
    if decision is None:
        return {"code": 0, "duplicate": stored.duplicate, "action_status": "ignored"}
    service = RemediationService(
        session,
        request.app.state.remediation_executor,
        request.app.state.remediation_approvers,
        locks=request.app.state.remediation_locks,
    )
    try:
        action, _ = await service.decide(
            card_action.action_id,
            card_action.actor,
            decision,
            card_action.comment,
        )
    except (RemediationNotFoundError, RemediationConflictError) as exc:
        return {
            "code": 0,
            "duplicate": stored.duplicate,
            "action_status": "rejected",
            "message": str(exc),
        }
    return {
        "code": 0,
        "duplicate": stored.duplicate,
        "action_status": action.status.value,
    }
