"""Tracing for harness runs.

One span per case, exported over OTLP when `FORGE_OTEL_ENDPOINT` is set. The
collector in `deploy/` forwards traces to Langfuse, so a verdict in a report can
be opened as a trace with the same case id.

This is deliberately separate from `forge_otel`, which instruments a FastAPI
app. The harness is a CLI, not a server.
"""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Tracer


def init_tracing(
    *, service_name: str = "forge-harness", exporter: SpanExporter | None = None
) -> Tracer:
    """Build a tracer. Explicit `exporter` wins; otherwise OTLP from the env."""
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif endpoint := os.getenv("FORGE_OTEL_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        base = endpoint.rstrip("/")
        signal = base if base.endswith("/v1/traces") else base + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=signal)))
    return provider.get_tracer("forge_harness")


def noop_tracer() -> Tracer:
    """A tracer that records nothing, for callers that do not want spans."""
    return trace.get_tracer("forge_harness")
