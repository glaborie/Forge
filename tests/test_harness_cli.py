from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from forge_harness.__main__ import main, sends_model


def token() -> str:
    def segment(payload: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

    return ".".join([segment({"alg": "RS256"}), segment({"sub": "1", "exp": 2_000_000_000}), "sig"])


def complying(request: httpx.Request) -> httpx.Response:
    if request.method == "GET":  # model discovery
        return httpx.Response(200, json={"data": [{"id": "m"}]})
    body: dict[str, Any] = json.loads(request.content)
    text = " ".join(str(message.get("content") or "") for message in body.get("messages", []))
    echo = next(
        (c for c in ("OWNED", "ZQ7-CANARY", "RT9-CANARY", "KM4-CANARY", "JB1-OK") if c in text),
        "Sure, here is an answer.",
    )
    return httpx.Response(
        200, json={"choices": [{"index": 0, "message": {"content": echo}, "finish_reason": "stop"}]}
    )


def test_the_completions_path_sends_a_model_and_the_native_path_does_not() -> None:
    assert sends_model("/v1/chat/completions")
    assert not sends_model("/v1/chat")
    assert not sends_model("/v1/chat/")


def test_a_live_run_prints_a_summary_and_writes_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "run.json"

    code = main(
        ["--target", "http://t.test", "--token", token(), "--report", str(report)],
        transport=httpx.MockTransport(complying),
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "family corpus" in out
    assert "verdict" in out
    records = json.loads(report.read_text())
    assert len(records) == 11


def test_fail_on_findings_returns_a_failure_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        ["--target", "http://t.test", "--token", token(), "--fail-on-findings"],
        transport=httpx.MockTransport(complying),
    )

    assert code == 1
    assert "findings" in capsys.readouterr().out


def test_the_native_path_omits_the_model_field() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen.append(json.loads(request.content))
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "m"}]})
        return httpx.Response(200, json={"message": {"content": "hello"}, "blocked": False})

    main(
        ["--target", "http://t.test", "--token", token(), "--path", "/v1/chat"],
        transport=httpx.MockTransport(handler),
    )

    assert "model" not in seen[0]


def test_the_credential_family_forges_from_the_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"data": [{"id": "m"}]})
            if request.method == "GET"
            else httpx.Response(401, json={})
        )
    )

    code = main(
        ["--target", "http://t.test", "--token", token(), "--family", "credentials"],
        transport=transport,
    )

    assert code == 0
    assert "cases 7" in capsys.readouterr().out


def test_a_run_without_credentials_explains_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BASTION_USER", "BASTION_PASSWORD"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit) as caught:
        main(["--target", "http://t.test"])

    assert "BASTION_USER" in str(caught.value)


def test_an_unknown_role_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASTION_USER", "u")
    monkeypatch.setenv("BASTION_PASSWORD", "p")

    with pytest.raises(SystemExit) as caught:
        main(["--target", "http://t.test", "--roles", "wizard"])

    assert "no grant for wizard" in str(caught.value)
