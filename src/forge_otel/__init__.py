"""OpenTelemetry instrumentation for an agent that serves an OpenAI-compatible API.

Two hops are traced: the inbound request to the agent, and the outbound call it
makes to an LLM provider. The same calls also emit metrics (latency, tokens, cost)
so dashboards do not have to derive them from spans. See A1 and A2 in the project
backlog for the attribute and metric contracts.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.metrics import Counter, Histogram
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Span, Status, StatusCode

# USD per million tokens. Override with FORGE_OTEL_PRICES='{"model": {"input": 1, "output": 2}}'.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

_provider: TracerProvider | None = None
_metric_provider: MeterProvider | None = None
_tokens: Counter | None = None
_cost_metric: Counter | None = None
_duration: Histogram | None = None
_calls: Counter | None = None

# Set by the inbound middleware so the outbound span and its metrics can be
# attributed to a tenant without the caller having to thread it through.
_CURRENT_TENANT: ContextVar[str | None] = ContextVar("forge_tenant", default=None)

Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


def init_tracing(
    app: FastAPI,
    *,
    exporter: SpanExporter | None = None,
    metric_reader: MetricReader | None = None,
    service_name: str = "forge-agent",
) -> TracerProvider:
    """Configure tracing and metrics for `app`, and instrument its inbound requests.

    Passing `exporter`/`metric_reader` takes precedence over FORGE_OTEL_ENDPOINT.
    With neither, spans and metrics are created but not exported.
    """
    global _provider, _metric_provider, _tokens, _cost_metric, _duration, _calls

    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("FORGE_OTEL_ENDPOINT")
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=_signal_endpoint(endpoint, "traces")))
        )
    _provider = provider

    readers: list[MetricReader] = []
    if metric_reader is not None:
        readers.append(metric_reader)
    elif endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        interval = int(os.getenv("FORGE_OTEL_METRICS_INTERVAL_MS", "5000"))
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=_signal_endpoint(endpoint, "metrics")),
                export_interval_millis=interval,
            )
        )
    _metric_provider = MeterProvider(resource=resource, metric_readers=readers)
    meter = _metric_provider.get_meter("forge_otel")
    _tokens = meter.create_counter(
        "gen_ai.client.token.usage", unit="{token}", description="Tokens consumed per LLM call"
    )
    # No unit: the collector appends it to the metric name, and the name already
    # says usd. With unit="USD" this became forge_llm_cost_usd_USD_total.
    _cost_metric = meter.create_counter(
        "forge.llm.cost.usd", description="Estimated cost per LLM call"
    )
    # Explicit boundaries: the SDK defaults are sized for milliseconds, but this
    # instrument is in seconds, so every observation would land in the first
    # bucket and quantiles would be meaningless.
    _duration = meter.create_histogram(
        "gen_ai.client.operation.duration",
        unit="s",
        description="Outbound LLM call latency",
        explicit_bucket_boundaries_advisory=[
            0.01,
            0.02,
            0.04,
            0.08,
            0.16,
            0.32,
            0.64,
            1.28,
            2.56,
            5.12,
            10.24,
            20.48,
            40.96,
        ],
    )
    _calls = meter.create_counter(
        "forge.llm.calls", unit="{call}", description="Outbound LLM calls, tagged by outcome"
    )

    # Added first so it runs inside the server span the instrumentor installs.
    app.add_middleware(_InboundAttributes)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    return provider


@dataclass
class LLMCall:
    """Handle returned by `llm_call`, used to record the provider's reply."""

    span: Span
    model: str

    def record_response(
        self,
        *,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        completion: str | None = None,
    ) -> None:
        if model:
            self.span.set_attribute("gen_ai.response.model", model)
        if input_tokens is not None:
            self.span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        if output_tokens is not None:
            self.span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        if completion is not None:
            _record_text(self.span, "completion", completion)
        attrs = _metric_attributes(self.model)
        if input_tokens is not None and _tokens is not None:
            _tokens.add(input_tokens, {**attrs, "gen_ai.token.type": "input"})
        if output_tokens is not None and _tokens is not None:
            _tokens.add(output_tokens, {**attrs, "gen_ai.token.type": "output"})
        if input_tokens is not None and output_tokens is not None:
            cost = _cost(self.model, input_tokens, output_tokens)
            if cost is not None:
                self.span.set_attribute("llm.cost.usd", cost)
                if _cost_metric is not None:
                    _cost_metric.add(cost, attrs)


@contextmanager
def llm_call(*, provider: str, model: str, prompt: str | None = None) -> Iterator[LLMCall]:
    """Trace the outbound call to an LLM provider."""
    started = time.monotonic()
    with _tracer().start_as_current_span(
        f"chat {model}", record_exception=False, set_status_on_exception=False
    ) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", provider)
        span.set_attribute("gen_ai.request.model", model)
        if tenant := _CURRENT_TENANT.get():
            span.set_attribute("tenant.id", tenant)
        if prompt is not None:
            _record_text(span, "prompt", prompt)
        failed = False
        try:
            yield LLMCall(span=span, model=model)
        except Exception as exc:
            failed = True
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            span.record_exception(exc)
            raise
        finally:
            attrs = _metric_attributes(model)
            if _duration is not None:
                _duration.record(time.monotonic() - started, attrs)
            if _calls is not None:
                _calls.add(1, {**attrs, "error": "true" if failed else "false"})


class _InboundAttributes:
    """Attach request.id, tenant.id and gen_ai.request.model to the server span."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Message, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        span = trace.get_current_span()
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers") or []
        }
        span.set_attribute("request.id", headers.get("x-request-id") or uuid.uuid4().hex)
        if tenant := headers.get("x-tenant-id"):
            span.set_attribute("tenant.id", tenant)
            _CURRENT_TENANT.set(tenant)

        async def send_and_capture(message: Message) -> None:
            if message["type"] == "http.response.start":
                span.set_attribute("http.response.status_code", message["status"])
            await send(message)

        if scope["method"] != "POST" or not scope["path"].endswith("/chat/completions"):
            await self.app(scope, receive, send_and_capture)
            return

        body = bytearray()

        async def receive_and_capture() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    _record_request_model(span, body)
            return message

        await self.app(scope, receive_and_capture, send_and_capture)


def _record_request_model(span: Span, body: bytearray) -> None:
    try:
        model = json.loads(body).get("model")
    except (json.JSONDecodeError, AttributeError):
        return
    if isinstance(model, str) and model:
        span.set_attribute("gen_ai.request.model", model)


def _signal_endpoint(base: str, signal: str) -> str:
    """FORGE_OTEL_ENDPOINT is a collector base URL; exporters need the signal path."""
    base = base.rstrip("/")
    suffix = f"/v1/{signal}"
    return base if base.endswith(suffix) else base + suffix


def _metric_attributes(model: str) -> dict[str, str]:
    attrs = {"gen_ai.request.model": model, "gen_ai.operation.name": "chat"}
    if tenant := _CURRENT_TENANT.get():
        attrs["tenant.id"] = tenant
    return attrs


def _tracer() -> trace.Tracer:
    return (_provider or trace.get_tracer_provider()).get_tracer("forge_otel")


def _captures_content() -> bool:
    return os.getenv("FORGE_OTEL_CAPTURE_CONTENT", "1") != "0"


def _record_text(span: Span, kind: str, text: str) -> None:
    span.set_attribute(f"{kind}.sha256", hashlib.sha256(text.encode()).hexdigest())
    if _captures_content():
        span.set_attribute(f"{kind}.text", text)


def _cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    prices = dict(DEFAULT_PRICES)
    if raw := os.getenv("FORGE_OTEL_PRICES"):
        for name, value in json.loads(raw).items():
            prices[name] = (float(value["input"]), float(value["output"]))
    price = prices.get(model)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
