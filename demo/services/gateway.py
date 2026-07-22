from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, status
from opentelemetry.propagate import inject

from demo.services.common import (
    FaultController,
    ServiceMetrics,
    install_standard_endpoints,
    instrument_app,
)


def create_app(
    order_client: httpx.AsyncClient | None = None,
    fault_token: str | None = None,
) -> FastAPI:
    owns_client = order_client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.order_client is None:
            app.state.order_client = httpx.AsyncClient(
                base_url=os.getenv("ORDER_SERVICE_URL", "http://order:8081"),
                timeout=httpx.Timeout(8.0),
            )
        yield
        if owns_client:
            await app.state.order_client.aclose()

    app = FastAPI(title="OpsPilot Demo API Gateway", version="0.1.0", lifespan=lifespan)
    app.state.order_client = order_client
    controller = FaultController()
    tracer = instrument_app(app, "api-gateway")
    install_standard_endpoints(
        app,
        "api-gateway",
        controller,
        fault_token if fault_token is not None else os.getenv("DEMO_FAULT_TOKEN", "demo-only"),
    )
    ServiceMetrics("api-gateway").install(app)

    @app.post("/api/v1/orders", tags=["gateway"])
    async def create_order(payload: dict[str, Any]) -> dict[str, Any]:
        await controller.apply()
        headers: dict[str, str] = {}
        inject(headers)
        with tracer.start_as_current_span("order.create"):
            try:
                response = await app.state.order_client.post(
                    "/api/v1/orders", json=payload, headers=headers
                )
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "ORDER_UNAVAILABLE", "message": str(exc)},
                ) from exc
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        return response.json()

    app.state.fault_controller = controller
    return app


app = create_app()
