"""Fetch and cache a bearer token from Keycloak.

Credentials come from the environment, never from code or chat:

    BASTION_TOKEN_URL   default http://localhost:8080/realms/bastion/protocol/openid-connect/token
    BASTION_CLIENT_ID   default bastion-cli
    BASTION_USERNAME or BASTION_USER
    BASTION_PASSWORD
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import httpx

DEFAULT_TOKEN_URL = "http://localhost:8080/realms/bastion/protocol/openid-connect/token"
DEFAULT_CLIENT_ID = "bastion-cli"


class TokenError(RuntimeError):
    """Keycloak refused the grant, or the response did not contain a token."""


class KeycloakPasswordGrant:
    """A callable that returns a cached access token and refreshes it before expiry."""

    def __init__(
        self,
        *,
        token_url: str | None = None,
        client_id: str | None = None,
        username: str | None = None,
        password: str | None = None,
        scope: str = "openid profile email",
        timeout: float = 15.0,
        refresh_margin: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.token_url = token_url or os.getenv("BASTION_TOKEN_URL") or DEFAULT_TOKEN_URL
        self.client_id = client_id or os.getenv("BASTION_CLIENT_ID") or DEFAULT_CLIENT_ID
        self.username = username or os.getenv("BASTION_USERNAME") or os.getenv("BASTION_USER")
        self.password = password or os.getenv("BASTION_PASSWORD")
        self.scope = scope
        self.refresh_margin = refresh_margin
        self._clock = clock
        self._token: str | None = None
        self._expires_at = 0.0
        self._client = httpx.Client(timeout=timeout, transport=transport)

        if not self.username or not self.password:
            raise ValueError(
                "missing credentials: set BASTION_USERNAME (or BASTION_USER) and "
                "BASTION_PASSWORD, or pass them"
            )

    def __call__(self) -> str:
        if self._token and self._clock() < self._expires_at:
            return self._token
        return self._refresh()

    def _refresh(self) -> str:
        response = self._client.post(
            self.token_url,
            data={
                "grant_type": "password",
                "client_id": self.client_id,
                "username": self.username,
                "password": self.password,
                "scope": self.scope,
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TokenError(f"HTTP {response.status_code}: {response.text[:200]}") from exc
        if response.status_code >= 400 or "access_token" not in payload:
            detail = payload.get("error_description") or payload.get("error") or response.text[:200]
            raise TokenError(f"HTTP {response.status_code}: {detail}")

        self._token = str(payload["access_token"])
        lifetime = float(payload.get("expires_in", 60))
        self._expires_at = self._clock() + max(lifetime - self.refresh_margin, 0.0)
        return self._token
