"""Minimal OpenAI-compatible upstream. Deterministic, no API key, no network."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

app = FastAPI()
MODEL = "gpt-4o-mini"


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {"object": "list", "data": [{"id": MODEL, "object": "model"}]}


@app.post("/v1/chat/completions")
def chat_completion(payload: dict[str, Any]) -> dict[str, Any]:
    model = payload.get("model") or MODEL
    if model == "explode":
        raise HTTPException(status_code=500, detail="upstream failure")

    prompt_tokens = sum(
        len(str(message.get("content", "")).split()) for message in payload.get("messages", [])
    )
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Mock reply."},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 2,
            "total_tokens": prompt_tokens + 2,
        },
    }
