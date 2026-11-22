from __future__ import annotations

import json

import httpx
import pytest

from forge_eval import RUBRICS, Evaluator, JudgeError, Sample
from forge_eval.openrouter import ask


def transport_returning(content: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "test/judge"
        assert body["temperature"] == 0
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})

    return httpx.MockTransport(handler)


def test_the_adapter_sends_the_prompt_and_returns_the_content() -> None:
    complete = ask(
        model="test/judge", api_key="test-key", transport=transport_returning('{"score": 1}')
    )

    assert complete("judge this") == '{"score": 1}'


def test_an_http_failure_becomes_a_judge_error() -> None:
    complete = ask(
        model="test/judge", api_key="test-key", transport=transport_returning("boom", status=500)
    )

    with pytest.raises(JudgeError) as caught:
        complete("judge this")

    assert "judge request failed" in str(caught.value)


def test_a_missing_api_key_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValueError) as caught:
        ask(model="test/judge")

    assert "OPENROUTER_API_KEY" in str(caught.value)


def test_environment_variables_fill_in_the_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_MODEL", "test/judge")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://judge.test/api/v1")

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    ask(transport=httpx.MockTransport(handler))("prompt")

    assert seen == ["https://judge.test/api/v1/chat/completions"]


def test_the_adapter_and_the_evaluator_compose() -> None:
    evaluator = Evaluator(
        ask=ask(
            model="test/judge",
            api_key="test-key",
            transport=transport_returning(json.dumps({"score": 0.4, "reason": "partial"})),
        ),
        rubric=RUBRICS["relevance"],
        model="test/judge",
    )

    score = evaluator.evaluate(Sample(input="q", output="a"))

    assert (score.value, score.reason, score.mode) == (0.4, "partial", "reference-free")
