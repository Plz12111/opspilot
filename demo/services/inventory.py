from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from demo.services.common import (
    FaultController,
    ServiceMetrics,
    install_standard_endpoints,
    instrument_app,
)


class ReservationRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0, le=100)


class ReservationResponse(BaseModel):
    reservation_id: str
    order_id: str
    sku: str
    quantity: int
    remaining: int


def create_app(fault_token: str | None = None) -> FastAPI:
    app = FastAPI(title="OpsPilot Demo Inventory Service", version="0.1.0")
    controller = FaultController()
    stocks = {"SKU-001": 100, "SKU-002": 50}
    reservations: dict[str, ReservationResponse] = {}
    stock_lock = asyncio.Lock()

    install_standard_endpoints(
        app,
        "inventory-service",
        controller,
        fault_token if fault_token is not None else os.getenv("DEMO_FAULT_TOKEN", "demo-only"),
    )
    ServiceMetrics("inventory-service").install(app)
    instrument_app(app, "inventory-service")

    @app.post(
        "/api/v1/inventory/reservations",
        response_model=ReservationResponse,
        tags=["inventory"],
    )
    async def reserve(request: ReservationRequest) -> ReservationResponse:
        await controller.apply()
        async with stock_lock:
            if existing := reservations.get(request.order_id):
                return existing
            available = stocks.get(request.sku, 0)
            if available < request.quantity:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "INSUFFICIENT_STOCK", "available": available},
                )
            remaining = available - request.quantity
            stocks[request.sku] = remaining
            result = ReservationResponse(
                reservation_id=f"res-{request.order_id}",
                order_id=request.order_id,
                sku=request.sku,
                quantity=request.quantity,
                remaining=remaining,
            )
            reservations[request.order_id] = result
            return result

    app.state.fault_controller = controller
    return app


app = create_app()
