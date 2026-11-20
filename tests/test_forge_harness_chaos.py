from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from forge_harness import Case, Runner, Target
from forge_harness.chaos import assemble, credential_cases, split


def sample_token() -> str:
    def enc(data: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    header = {"alg": "RS256", "typ": "JWT", "kid": "test"}
    payload = {
        "sub": "abc",
        "exp": 2_000_000_000,
        "aud": "bastion",
        "realm_access": {"roles": ["admin"]},
    }
    return f"{enc(header)}.{enc(payload)}.c2lnbmF0dXJl"


def test_case_family_is_complete_and_all_expect_denial() -> None:
    cases = credential_cases(sample_token())

    assert len(cases) == 7
    assert {case.expectation for case in cases} == {"denied"}
    assert all(case.token and case.token != sample_token() for case in cases)
    assert all("credential" in case.tags for case in cases)


def test_claim_cases_are_marked_as_signature_broken_too() -> None:
    """We hold no signing key, so an 'expired' token is also a tampered one."""
    cases = {case.id: case for case in credential_cases(sample_token())}

    assert "signature-broken-too" in cases["cred-05-expired-claim"].tags
    assert "signature-broken-too" not in cases["cred-01-tampered-signature"].tags


def test_split_and_assemble_round_trip() -> None:
    token = sample_token()
    header, payload, signature = split(token)

    assert assemble(header, payload, signature) == token


def test_a_rejected_forgery_is_a_denial() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, json={"error": {"message": "invalid token"}})
    )
    case = Case(id="cred", prompt="hi", expectation="denied", token="forged")
    run = Runner().run(
        [case], Target("http://t.test", model="m", token="real", transport=transport)
    )

    assert run.records[0].verdict == "denied"
    assert run.summary()["unexpected_access"] == 0


def test_an_accepted_forgery_is_unexpected_access() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"choices": [{"message": {"content": "Hello!"}}]})
    )
    case = Case(id="cred", prompt="hi", expectation="denied", token="forged")
    run = Runner().run(
        [case], Target("http://t.test", model="m", token="real", transport=transport)
    )

    assert run.records[0].verdict == "unexpected_access"
    assert run.summary()["unexpected_access"] == 1


def test_the_case_token_replaces_the_target_token() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(401, json={})

    case = Case(id="cred", prompt="hi", expectation="denied", token="forged-token")
    Runner().run(
        [case],
        Target(
            "http://t.test", model="m", token="valid-token", transport=httpx.MockTransport(handler)
        ),
    )

    assert seen == ["Bearer forged-token"]
