"""Generate forged credentials from one valid token.

Everything here is unsigned-by-attacker by construction: we do not hold the
realm's signing key, so any change to the payload invalidates the signature. That
is the honest limit of this family — a rejection proves "the gateway rejects a
tampered token", not "the gateway rejects an expired token". Claim-level cases
(expired, wrong audience, injected role) are marked so a report never overstates
them.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from . import Case


def _b64d(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def split(token: str) -> tuple[dict[str, Any], dict[str, Any], str]:
    header, payload, signature = token.split(".")
    return json.loads(_b64d(header)), json.loads(_b64d(payload)), signature


def assemble(header: dict[str, Any], payload: dict[str, Any], signature: str) -> str:
    return f"{_b64e(json.dumps(header).encode())}.{_b64e(json.dumps(payload).encode())}.{signature}"


def credential_cases(valid_token: str) -> list[Case]:
    """Forged variants of a real token, each a case that must be refused."""
    header, payload, signature = split(valid_token)
    flipped = signature[:-1] + ("A" if signature[-1] != "A" else "B")
    no_alg = {**header, "alg": "none"}

    expired = {**payload, "exp": 1}
    wrong_aud = {**payload, "aud": "some-other-service"}
    existing = payload.get("realm_access", {}).get("roles", [])
    escalated = sorted({*existing, "admin"})
    if escalated == sorted(existing):
        # Already admin: escalate to a role that is not ours, so the case is
        # still a forgery rather than a byte-identical copy of the real token.
        escalated = sorted({*existing, "break-glass"})
    injected_roles = {**payload, "realm_access": {"roles": escalated}}

    return [
        Case(
            id="cred-01-tampered-signature",
            prompt="Say hello.",
            expectation="denied",
            tags=("credential", "signature"),
            token=assemble(header, payload, flipped),
        ),
        Case(
            id="cred-02-alg-none",
            prompt="Say hello.",
            expectation="denied",
            tags=("credential", "algorithm"),
            token=assemble(no_alg, payload, ""),
        ),
        Case(
            id="cred-03-truncated",
            prompt="Say hello.",
            expectation="denied",
            tags=("credential", "malformed"),
            token=".".join(valid_token.split(".")[:2]) + ".",
        ),
        Case(
            id="cred-04-garbage",
            prompt="Say hello.",
            expectation="denied",
            tags=("credential", "malformed"),
            token="not-a-jwt",
        ),
        Case(
            id="cred-05-expired-claim",
            prompt="Say hello.",
            expectation="denied",
            tags=("credential", "claim", "signature-broken-too"),
            token=assemble(header, expired, signature),
        ),
        Case(
            id="cred-06-wrong-audience",
            prompt="Say hello.",
            expectation="denied",
            tags=("credential", "claim", "signature-broken-too"),
            token=assemble(header, wrong_aud, signature),
        ),
        Case(
            id="cred-07-injected-role",
            prompt="Say hello.",
            expectation="denied",
            tags=("credential", "claim", "signature-broken-too"),
            token=assemble(header, injected_roles, signature),
        ),
    ]
