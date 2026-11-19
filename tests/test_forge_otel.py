from __future__ import annotations

from typing import Any

import pytest
from fake_upstream import app as upstream_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

import forge_otel

upstream = TestClient(upstream_app)


def agent_client(exporter: InMemorySpanExporter) -> TestClient:
    """An agent that fronts the mock upstream over an OpenAI-compatible endpoint."""
    app = FastAPI()
    forge_otel.init_tracing(app, exporter=exporter)

    @app.post("/v1/chat/completions")
    def chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
        prompt = payload["messages"][-1]["content"]
        with forge_otel.llm_call(provider="openai", model=payload["model"], prompt=prompt) as call:
            response = upstream.post("/v1/chat/completions", json=payload)
            response.raise_for_status()
            data = response.json()
            call.record_response(
                model=data["model"],
                input_tokens=data["usage"]["prompt_tokens"],
                output_tokens=data["usage"]["completion_tokens"],
                completion=data["choices"][0]["message"]["content"],
            )
        return data

    return TestClient(app, raise_server_exceptions=False)


def request(client: TestClient, model: str = "gpt-4o-mini") -> Any:
    return client.post(
        "/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hello there"}]},
        headers={"x-tenant-id": "acme", "x-request-id": "req-1"},
    )


def spans_by_name(exporter: InMemorySpanExporter) -> dict[str, Any]:
    return {span.name: span for span in exporter.get_finished_spans()}


def span_of_kind(exporter: InMemorySpanExporter, kind: SpanKind) -> Any:
    return next(span for span in exporter.get_finished_spans() if span.kind is kind)


def test_both_hops_carry_the_contract_attributes() -> None:
    exporter = InMemorySpanExporter()
    response = request(agent_client(exporter))

    assert response.status_code == 200
    spans = spans_by_name(exporter)
    llm = spans["chat gpt-4o-mini"]
    server = span_of_kind(exporter, SpanKind.SERVER)

    assert server.attributes["request.id"] == "req-1"
    assert server.attributes["tenant.id"] == "acme"
    assert server.attributes["gen_ai.request.model"] == "gpt-4o-mini"
    assert server.attributes["http.response.status_code"] == 200

    assert llm.attributes["gen_ai.operation.name"] == "chat"
    assert llm.attributes["gen_ai.provider.name"] == "openai"
    assert llm.attributes["gen_ai.request.model"] == "gpt-4o-mini"
    assert llm.attributes["gen_ai.response.model"] == "gpt-4o-mini"
    assert llm.attributes["gen_ai.usage.input_tokens"] == 2
    assert llm.attributes["gen_ai.usage.output_tokens"] == 2
    assert llm.attributes["llm.cost.usd"] > 0
    assert llm.attributes["prompt.text"] == "hello there"
    assert llm.attributes["completion.text"] == "Mock reply."


def test_content_toggle_records_hashes_instead_of_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_OTEL_CAPTURE_CONTENT", "0")
    exporter = InMemorySpanExporter()
    request(agent_client(exporter))

    llm = spans_by_name(exporter)["chat gpt-4o-mini"]
    assert "prompt.text" not in llm.attributes
    assert "completion.text" not in llm.attributes
    assert len(llm.attributes["prompt.sha256"]) == 64
    assert len(llm.attributes["completion.sha256"]) == 64


def test_upstream_failure_marks_the_span_as_error() -> None:
    exporter = InMemorySpanExporter()
    response = request(agent_client(exporter), model="explode")

    assert response.status_code == 500
    llm = spans_by_name(exporter)["chat explode"]
    assert llm.status.status_code.name == "ERROR"
    assert [event.name for event in llm.events] == ["exception"]


def test_unknown_model_omits_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = InMemorySpanExporter()
    request(agent_client(exporter), model="not-in-the-price-map")

    assert "llm.cost.usd" not in spans_by_name(exporter)["chat not-in-the-price-map"].attributes


def test_no_endpoint_and_no_exporter_exports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORGE_OTEL_ENDPOINT", raising=False)

    def explode(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("an OTLP exporter was constructed without an endpoint")

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter", explode
    )
    forge_otel.init_tracing(FastAPI())


def test_endpoint_installs_an_otlp_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_OTEL_ENDPOINT", "http://localhost:4318/v1/traces")
    constructed: dict[str, Any] = {}

    class FakeExporter:
        def __init__(self, endpoint: str | None = None, **kwargs: Any) -> None:
            constructed["endpoint"] = endpoint

        def export(self, spans: Any) -> None:
            return None

        def shutdown(self) -> None:
            return None

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter", FakeExporter
    )
    forge_otel.init_tracing(FastAPI())

    assert constructed["endpoint"] == "http://localhost:4318/v1/traces"
