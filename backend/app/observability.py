from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.engine import Engine


_configured = False


def _resource() -> Resource:
    return Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "fulfillos-api"),
            "service.version": os.getenv("FULFILLOS_VERSION", "0.5.0"),
            "deployment.environment": os.getenv("VERCEL_ENV", os.getenv("ENVIRONMENT", "development")),
        }
    )


def configure_observability(app: FastAPI, engine: Engine) -> None:
    """Install OpenTelemetry traces/metrics and structured request logs.

    OTLP export is enabled when OTEL_EXPORTER_OTLP_ENDPOINT is configured.
    Without an exporter the instrumentation remains safe for local/test use.
    """
    global _configured
    if _configured:
        return
    _configured = True

    resource = _resource()
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()

    tracer_provider = TracerProvider(resource=resource)
    if otlp_endpoint:
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metric_readers = []
    if otlp_endpoint:
        metric_readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(),
                export_interval_millis=15_000,
            )
        )
    meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
    metrics.set_meter_provider(meter_provider)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
    SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=tracer_provider)

    meter = metrics.get_meter("fulfillos.http")
    request_counter = meter.create_counter(
        "fulfillos.http.requests",
        unit="1",
        description="HTTP requests handled by the FulfillOS API",
    )
    error_counter = meter.create_counter(
        "fulfillos.http.errors",
        unit="1",
        description="HTTP responses with status >= 500",
    )
    latency = meter.create_histogram(
        "fulfillos.http.duration",
        unit="ms",
        description="FulfillOS API request duration",
    )

    @app.middleware("http")
    async def request_metrics(request: Request, call_next):
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        status_code = 500
        response = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            attrs: dict[str, Any] = {
                "http.method": request.method,
                "http.route": route_path,
                "http.status_code": status_code,
            }
            request_counter.add(1, attrs)
            latency.record(duration_ms, attrs)
            if status_code >= 500:
                error_counter.add(1, attrs)
            if response is not None:
                response.headers["X-Request-ID"] = request_id
            print(
                json.dumps(
                    {
                        "type": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "route": route_path,
                        "status": status_code,
                        "duration_ms": round(duration_ms, 2),
                    },
                    separators=(",", ":"),
                )
            )
