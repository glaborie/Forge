from __future__ import annotations

import httpx
import pytest

from forge_harness import Target
from forge_harness.auth import KeycloakPasswordGrant, TokenError


def token_server(
    payload: dict[str, object], status: int = 200, counter: dict[str, int] | None = None
):
    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter["calls"] = counter.get("calls", 0) + 1
        assert request.url.path.endswith("/token")
        body = request.content.decode()
        assert "grant_type=password" in body
        assert "client_id=bastion-cli" in body
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def grant(transport: httpx.MockTransport, **kwargs: object) -> KeycloakPasswordGrant:
    return KeycloakPasswordGrant(
        username="user",
        password="pass",
        transport=transport,
        **kwargs,  # type: ignore[arg-type]
    )


def test_returns_the_access_token() -> None:
    g = grant(token_server({"access_token": "abc123", "expires_in": 300}))
    assert g() == "abc123"


def test_caches_until_expiry() -> None:
    counter: dict[str, int] = {}
    now = {"t": 0.0}
    g = grant(
        token_server({"access_token": "abc", "expires_in": 300}, counter=counter),
        clock=lambda: now["t"],
        refresh_margin=30,
    )

    assert g() == "abc"
    assert g() == "abc"
    assert counter["calls"] == 1

    now["t"] = 280.0  # inside the 30s margin
    assert g() == "abc"
    assert counter["calls"] == 2


def test_rejects_a_grant_error() -> None:
    g = grant(token_server({"error": "invalid_grant", "error_description": "bad credentials"}, 401))

    with pytest.raises(TokenError, match="bad credentials"):
        g()


def test_rejects_a_response_without_a_token() -> None:
    g = grant(token_server({"token_type": "Bearer"}))

    with pytest.raises(TokenError):
        g()


def test_missing_credentials_fail_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BASTION_USERNAME", raising=False)
    monkeypatch.delenv("BASTION_USER", raising=False)
    monkeypatch.delenv("BASTION_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="BASTION_USERNAME"):
        KeycloakPasswordGrant()


def test_target_resolves_a_callable_token_per_request(tmp_path: object) -> None:
    seen: list[str] = []
    calls = {"n": 0}

    def token() -> str:
        calls["n"] += 1
        return f"token-{calls['n']}"

    def target_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    target = Target(
        "http://t.test",
        model="test-model",
        token=token,
        transport=httpx.MockTransport(target_handler),
    )
    target.send("first")
    target.send("second")

    assert seen == ["Bearer token-1", "Bearer token-2"]


def test_username_alias_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BASTION_USERNAME", raising=False)
    monkeypatch.setenv("BASTION_USER", "aliased")
    monkeypatch.setenv("BASTION_PASSWORD", "pass")

    assert KeycloakPasswordGrant().username == "aliased"
