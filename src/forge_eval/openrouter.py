"""Judge backed by an OpenRouter model.

OpenRouter speaks the OpenAI chat-completions shape, so this is a thin adapter:
send the prompt, return the content, and let `Evaluator` parse it. Any transport
or HTTP failure becomes `JudgeError`, so a caller has one exception type to
handle whether the model is down or the JSON is unusable.
"""

from __future__ import annotations

import os
from collections.abc import Callable

import httpx

from . import JudgeError

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


def ask(
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> Callable[[str], str]:
    """Build an `Evaluator`-compatible judge callable.

    Resolution order is argument, then environment. `transport` exists so tests
    can supply `httpx.MockTransport` and never touch the network.
    """
    model = model or os.getenv("OPENROUTER_MODEL")
    base_url = (base_url or os.getenv("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")

    if not model:
        raise ValueError("no model: pass model= or set OPENROUTER_MODEL")
    if not api_key:
        raise ValueError("no API key: pass api_key= or set OPENROUTER_API_KEY")

    client = httpx.Client(
        base_url=base_url,
        timeout=timeout,
        transport=transport,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )

    def complete(prompt: str) -> str:
        payload = {
            "model": model,
            "temperature": 0,
            "max_tokens": 256,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            response = client.post("/chat/completions", json=payload)
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"])
        except Exception as exc:
            raise JudgeError(f"judge request failed: {exc}") from exc

    return complete
