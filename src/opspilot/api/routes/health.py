from __future__ import annotations

import asyncio
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from opspilot.api.dependencies import get_session

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    await session.execute(text("SELECT 1"))
    checks: dict[str, dict[str, Any]] = {"database": {"status": "up", "critical": True}}
    settings = request.app.state.settings
    if not settings.readiness_check_external:
        return {"status": "ready", "checks": checks}

    names = ["redis", "prometheus", "loki", "jaeger"]
    results = await asyncio.gather(
        _check_redis(settings.redis_url, settings.readiness_timeout_seconds),
        _check_http(settings.prometheus_url, "/-/ready", settings.readiness_timeout_seconds),
        _check_http(settings.loki_url, "/ready", settings.readiness_timeout_seconds),
        _check_http(settings.jaeger_url, "/", settings.readiness_timeout_seconds),
    )
    for name, available in zip(names, results, strict=True):
        checks[name] = {
            "status": "up" if available else "down",
            "critical": False,
        }
    critical_down = any(item["critical"] and item["status"] == "down" for item in checks.values())
    optional_down = any(
        not item["critical"] and item["status"] == "down" for item in checks.values()
    )
    if critical_down:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        readiness_status = "not_ready"
    elif optional_down:
        readiness_status = "degraded"
    else:
        readiness_status = "ready"
    return {"status": readiness_status, "checks": checks}


async def _check_http(base_url: str, path: str, timeout_seconds: float) -> bool:
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds) as client:
            result = await client.get(path)
        return result.status_code < 500
    except (httpx.HTTPError, ValueError):
        return False


async def _check_redis(url: str, timeout_seconds: float) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme not in {"redis", "rediss"} or host is None:
        return False
    port = parsed.port or (6380 if parsed.scheme == "rediss" else 6379)
    ssl = parsed.scheme == "rediss"
    writer = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ssl),
            timeout=timeout_seconds,
        )
        writer.write(b"*1\r\n$4\r\nPING\r\n")
        await writer.drain()
        reply = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds)
        return reply.startswith(b"+PONG")
    except (OSError, TimeoutError):
        return False
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()
