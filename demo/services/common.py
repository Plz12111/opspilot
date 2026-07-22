from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, Field


class FaultConfiguration(BaseModel):
    latency_ms: int = Field(default=0, ge=0, le=30_000)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class FaultController:
    def __init__(self) -> None:
        self.configuration = FaultConfiguration()
        self._lock = asyncio.Lock()

    async def update(self, configuration: FaultConfiguration) -> FaultConfiguration:
        async with self._lock:
            self.configuration = configuration.model_copy()
            return self.configuration.model_copy()

    async def reset(self) -> None:
        await self.update(FaultConfiguration())

    async def apply(self) -> None:
        configuration = self.configuration
        if configuration.latency_ms:
            await asyncio.sleep(configuration.latency_ms / 1000)
        if configuration.error_rate and random.random() < configuration.error_rate:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "INJECTED_FAILURE", "message": "demo fault injection"},
            )


class ServiceMetrics:
    def __init__(self, service_name: str) -> None:
        self.registry = CollectorRegistry()
        self.requests = Counter(
            "demo_http_requests_total",
            "Total HTTP requests handled by demo services",
            ["service", "method", "route", "status"],
            registry=self.registry,
        )
        self.duration = Histogram(
            "demo_http_request_duration_seconds",
            "HTTP request latency for demo services",
            ["service", "method", "route"],
            registry=self.registry,
        )
        self.service_name = service_name

    def install(self, app: FastAPI) -> None:
        @app.middleware("http")
        async def observe_request(request: Request, call_next):
            started = time.perf_counter()
            status_code = 500
            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            finally:
                route = request.scope.get("route")
                route_name = getattr(route, "path", request.url.path)
                labels = (self.service_name, request.method, route_name)
                self.requests.labels(*labels, str(status_code)).inc()
                self.duration.labels(*labels).observe(time.perf_counter() - started)

        @app.get("/metrics", include_in_schema=False)
        async def metrics() -> Response:
            return Response(generate_latest(self.registry), media_type=CONTENT_TYPE_LATEST)


def install_standard_endpoints(
    app: FastAPI,
    service_name: str,
    fault_controller: FaultController,
    fault_token: str,
) -> None:
    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": service_name}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> dict[str, str]:
        return {"status": "ready", "service": service_name}

    def authorize(token: str | None) -> None:
        if not fault_token or token != fault_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid fault token",
            )

    @app.get("/internal/faults", tags=["faults"])
    async def get_faults(
        token: Annotated[str | None, Header(alias="X-Fault-Token")] = None,
    ) -> FaultConfiguration:
        authorize(token)
        return fault_controller.configuration.model_copy()

    @app.put("/internal/faults", tags=["faults"])
    async def set_faults(
        configuration: FaultConfiguration,
        token: Annotated[str | None, Header(alias="X-Fault-Token")] = None,
    ) -> FaultConfiguration:
        authorize(token)
        return await fault_controller.update(configuration)

    @app.delete("/internal/faults", status_code=status.HTTP_204_NO_CONTENT, tags=["faults"])
    async def reset_faults(
        token: Annotated[str | None, Header(alias="X-Fault-Token")] = None,
    ) -> Response:
        authorize(token)
        await fault_controller.reset()
        return Response(status_code=status.HTTP_204_NO_CONTENT)


def instrument_app(app: FastAPI, service_name: str) -> trace.Tracer:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    if not endpoint:
        return trace.get_tracer(service_name)
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    return provider.get_tracer(service_name)
