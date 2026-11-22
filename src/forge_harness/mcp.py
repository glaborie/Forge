"""MCP tool calls as a corpus family.

The gateway exposes `/mcp` as JSON-RPC over POST with three non-standard headers:
`MCP-Protocol-Version`, `Mcp-Method` and (for a call) `Mcp-Name`. The server rejects
a header whose value disagrees with the body, so both are built from the same
arguments here rather than by hand.

Authentication is a client-credentials bearer token, not a user grant: the token
carries `aud: bastion-mcp` and a `tenant` claim. A case may override it with `""`
to send no `Authorization` header at all.

A case expects `allow` or `deny`. A case that expected a denial and got a success
is `unexpected_access` — that is the finding this family exists to produce.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

PROTOCOL_VERSION = "2026-07-28"
_META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
}

# Sentinel: a case with `token=None` uses the client's credential, `""` sends none.
_USE_CLIENT = object()


@dataclass(frozen=True)
class MCPCase:
    id: str
    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    expectation: str = "allow"
    note: str = ""
    token: str | None = None


@dataclass
class MCPReply:
    status: int
    text: str = ""
    is_error: bool = False
    error: str | None = None
    body: Any = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.is_error and self.error is None


@dataclass(frozen=True)
class MCPRecord:
    case_id: str
    tool: str
    status: int
    verdict: str
    detail: str


@dataclass
class MCPRun:
    records: list[MCPRecord] = field(default_factory=list)

    def findings(self) -> list[MCPRecord]:
        return [r for r in self.records if r.verdict in ("unexpected_access", "unexpected_denial")]

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.verdict] = counts.get(record.verdict, 0) + 1
        return {"cases": len(self.records), "by_verdict": counts, "findings": len(self.findings())}

    def to_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"summary": self.summary(), "records": [asdict(r) for r in self.records]}
        path.write_text(json.dumps(payload, indent=2) + "\n")


class MCPError(RuntimeError):
    """The MCP endpoint could not be read at all."""


class MCPClient:
    """Minimal stateless MCP client: `tools/list` and `tools/call` over HTTP POST."""

    def __init__(
        self,
        base_url: str,
        *,
        path: str = "/mcp",
        token: str | Callable[[], str] | None = None,
        protocol_version: str = PROTOCOL_VERSION,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.path = path
        self.token = token
        self.protocol_version = protocol_version
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    def _credential(self) -> str | None:
        return self.token() if callable(self.token) else self.token

    def _post(
        self,
        method: str,
        *,
        params: dict[str, Any] | None = None,
        name: str | None = None,
        token: object = _USE_CLIENT,
    ) -> MCPReply:
        credential = self._credential() if token is _USE_CLIENT else token
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "MCP-Protocol-Version": self.protocol_version,
            "Mcp-Method": method,
        }
        if name is not None:
            headers["Mcp-Name"] = name
        if credential:
            headers["Authorization"] = f"Bearer {credential}"

        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": {**(params or {}), "_meta": _META},
        }
        try:
            response = self.client.post(self.path, json=body, headers=headers)
        except httpx.HTTPError as exc:
            return MCPReply(status=0, error=f"transport error: {exc}")

        try:
            data = response.json()
        except ValueError:
            return MCPReply(status=response.status_code, error=response.text[:200])

        if not isinstance(data, dict):
            return MCPReply(
                status=response.status_code, body=data, error="response was not an object"
            )

        error = data.get("error")
        if isinstance(error, dict):
            return MCPReply(
                status=response.status_code,
                error=str(error.get("message") or error),
                body=data,
            )

        result = data.get("result") or {}
        content = result.get("content") or []
        text = ""
        if content and isinstance(content[0], dict):
            text = str(content[0].get("text", ""))
        return MCPReply(
            status=response.status_code,
            text=text,
            is_error=bool(result.get("isError")),
            body=data,
        )

    def list_tools(self) -> list[dict[str, Any]]:
        reply = self._post("tools/list", params={})
        if not reply.ok:
            raise MCPError(reply.error or f"tools/list failed with {reply.status}")
        tools = (reply.body or {}).get("result", {}).get("tools", [])
        return [tool for tool in tools if isinstance(tool, dict)]

    def call(
        self, tool: str, arguments: dict[str, Any] | None = None, *, token: object = _USE_CLIENT
    ) -> MCPReply:
        return self._post(
            "tools/call",
            params={"name": tool, "arguments": arguments or {}},
            name=tool,
            token=token,
        )


def verdict_for(case: MCPCase, reply: MCPReply) -> str:
    if reply.status == 0:
        return "error"
    # 401 on a case that sent a credential means our own token was rejected: no
    # tool was judged, and counting it as a denial would pass every deny case
    # vacuously. The explicit no-token case is the one place a 401 is the answer.
    if reply.status == 401 and case.token != "":
        return "error"
    if case.expectation == "deny":
        return "denied" if not reply.ok else "unexpected_access"
    return "allowed" if reply.ok else "unexpected_denial"


def run_cases(client: MCPClient, cases: Iterable[MCPCase]) -> MCPRun:
    records: list[MCPRecord] = []
    for case in cases:
        token: object = _USE_CLIENT if case.token is None else case.token
        reply = client.call(case.tool, case.arguments, token=token)
        detail = reply.error or reply.text or f"status {reply.status}"
        if reply.status == 401 and case.token != "":
            detail = f"unauthenticated: {detail}"
        records.append(
            MCPRecord(
                case_id=case.id,
                tool=case.tool,
                status=reply.status,
                verdict=verdict_for(case, reply),
                detail=detail[:200],
            )
        )
    return MCPRun(records=records)


def load_mcp_corpus(path: str | Path) -> list[MCPCase]:
    data = json.loads(Path(path).read_text())
    rows = data if isinstance(data, list) else data.get("cases", [])
    return [
        MCPCase(
            id=str(row["id"]),
            tool=str(row["tool"]),
            arguments=dict(row.get("arguments") or {}),
            expectation=str(row.get("expectation", "allow")),
            note=str(row.get("note", "")),
            token=row.get("token"),
        )
        for row in rows
    ]
