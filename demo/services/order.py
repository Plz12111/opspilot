from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, status
from opentelemetry.propagate import inject
from pydantic import BaseModel, Field

from demo.services.common import (
    FaultController,
    ServiceMetrics,
    install_standard_endpoints,
    instrument_app,
)


class CreateOrderRequest(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0, le=100)
    order_id: str | None = Field(default=None, min_length=1, max_length=64)


class CreateOrderResponse(BaseModel):
    order_id: str
    status: str
    reservation_id: str


def create_app(
    inventory_client: httpx.AsyncClient | None = None,
    fault_token: str | None = None,
) -> FastAPI:
    owns_client = inventory_client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if app.state.inventory_client is None:
            app.state.inventory_client = httpx.AsyncClient(
                base_url=os.getenv("INVENTORY_SERVICE_URL", "http://inventory:8082"),
                timeout=httpx.Timeout(5.0),
            )
        yield
        if owns_client:
            await app.state.inventory_client.aclose()

    app = FastAPI(title="OpsPilot Demo Order Service", version="0.1.0", lifespan=lifespan)
    app.state.inventory_client = inventory_client
    controller = FaultController()
    tracer = instrument_app(app, "order-service")
    install_standard_endpoints(
        app,
        "order-service",
        controller,
        fault_token if fault_token is not None else os.getenv("DEMO_FAULT_TOKEN", "demo-only"),
    )
    ServiceMetrics("order-service").install(app)

    @app.post("/api/v1/orders", response_model=CreateOrderResponse, tags=["orders"])
    async def create_order(request: CreateOrderRequest) -> CreateOrderResponse:
        await controller.apply()
        order_id = request.order_id or uuid.uuid4().hex
        headers: dict[str, str] = {}
        inject(headers)
        with tracer.start_as_current_span("inventory.reserve"):
            try:
                response = await app.state.inventory_client.post(
                    "/api/v1/inventory/reservations",
                    json={"order_id": order_id, "sku": request.sku, "quantity": request.quantity},
                    headers=headers,
                )
            except httpx.RequestError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={"code": "INVENTORY_UNAVAILABLE", "message": str(exc)},
                ) from exc
        if response.status_code >= 500:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "INVENTORY_UNAVAILABLE", "upstream_status": response.status_code},
            )
        if response.status_code == status.HTTP_409_CONFLICT:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=response.json())
        response.raise_for_status()
        reservation = response.json()
        return CreateOrderResponse(
            order_id=order_id,
            status="CONFIRMED",
            reservation_id=reservation["reservation_id"],
        )

    app.state.fault_controller = controller
    return app


app = create_app()
