from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from forge_harness.__main__ import main
from forge_harness.mcp import (
    MCPCase,
    MCPClient,
    MCPError,
    load_mcp_corpus,
    run_cases,
    verdict_for,
)

CORPUS = Path(__file__).resolve().parents[1] / "harness" / "corpus" / "mcp.json"


def ok(text: str = '{"status": "executed"}') -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


def tool_error(message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": json.dumps({"error": message})}],
            "isError": True,
        },
    }


def rpc_error(code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "error": {"code": code, "message": message}}


def client_for(body: Any, status: int = 200, seen: list[httpx.Request] | None = None) -> MCPClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body)

    return MCPClient("http://t.test", token="tok", transport=httpx.MockTransport(handler))


def test_a_call_sends_the_jsonrpc_envelope_and_the_mcp_headers() -> None:
    seen: list[httpx.Request] = []
    client = client_for(ok(), seen=seen)

    reply = client.call("read_system_status", {})

    request = seen[0]
    assert request.url.path == "/mcp"
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["mcp-protocol-version"] == "2026-07-28"
    assert request.headers["mcp-method"] == "tools/call"
    assert request.headers["mcp-name"] == "read_system_status"
    body = json.loads(request.content)
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "read_system_status"
    assert body["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] == "2026-07-28"
    assert reply.ok and reply.text == '{"status": "executed"}'


def test_a_tool_level_error_is_flagged_but_still_carries_the_text() -> None:
    reply = client_for(tool_error("path escapes the tool workspace")).call(
        "read_file", {"path": "../x"}
    )

    assert not reply.ok
    assert reply.is_error
    assert "escapes" in reply.text


def test_a_jsonrpc_error_is_captured_as_the_message() -> None:
    reply = client_for(rpc_error(-32003, "unknown tool: 'rm_rf'"), status=400).call("rm_rf", {})

    assert not reply.ok
    assert reply.error == "unknown tool: 'rm_rf'"


def test_a_transport_failure_is_status_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = MCPClient("http://t.test", token="tok", transport=httpx.MockTransport(handler))

    reply = client.call("read_system_status", {})

    assert reply.status == 0
    assert "transport error" in (reply.error or "")


def test_an_empty_token_sends_no_authorization_header() -> None:
    seen: list[httpx.Request] = []
    client = client_for(
        rpc_error(-32001, "missing or malformed bearer token"), status=401, seen=seen
    )

    client.call("read_system_status", {}, token="")

    assert "authorization" not in seen[0].headers


def test_verdicts_follow_the_expectation() -> None:
    deny = MCPCase(id="c", tool="t", expectation="deny")
    allow = MCPCase(id="c", tool="t", expectation="allow")

    assert verdict_for(deny, client_for(ok()).call("t")) == "unexpected_access"
    assert verdict_for(deny, client_for(tool_error("no")).call("t")) == "denied"
    assert verdict_for(allow, client_for(ok()).call("t")) == "allowed"
    assert verdict_for(allow, client_for(tool_error("no")).call("t")) == "unexpected_denial"


def test_a_dead_endpoint_is_an_error_not_a_denial() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = MCPClient("http://t.test", token="tok", transport=httpx.MockTransport(handler))
    run = run_cases(client, [MCPCase(id="c", tool="read_system_status", expectation="deny")])

    assert run.summary()["by_verdict"] == {"error": 1}
    assert run.findings() == []


def test_a_rejected_credential_is_an_error_not_a_denial() -> None:
    """Otherwise every deny case passes vacuously on an expired token."""
    reply = client_for(rpc_error(-32001, "invalid bearer token"), status=401).call("read_file")

    assert verdict_for(MCPCase(id="c", tool="read_file", expectation="deny"), reply) == "error"
    # The case that deliberately sends nothing is the one 401 that means denial.
    assert (
        verdict_for(MCPCase(id="c", tool="read_file", expectation="deny", token=""), reply)
        == "denied"
    )


def test_findings_name_the_case_that_got_through() -> None:
    client = client_for(ok())
    run = run_cases(
        client,
        [
            MCPCase(id="should-pass", tool="read_system_status", expectation="allow"),
            MCPCase(id="should-fail", tool="read_file", expectation="deny"),
        ],
    )

    assert [finding.case_id for finding in run.findings()] == ["should-fail"]
    assert run.summary() == {
        "cases": 2,
        "by_verdict": {"allowed": 1, "unexpected_access": 1},
        "findings": 1,
    }


def test_the_run_writes_a_report(tmp_path: Path) -> None:
    run = run_cases(client_for(ok()), [MCPCase(id="c", tool="t")])
    path = tmp_path / "mcp.json"

    run.to_json(path)

    data = json.loads(path.read_text())
    assert data["summary"]["cases"] == 1
    assert data["records"][0]["case_id"] == "c"


def test_the_committed_corpus_covers_the_attack_shapes() -> None:
    cases = load_mcp_corpus(CORPUS)

    assert len({case.id for case in cases}) == len(cases) == 10
    assert {case.expectation for case in cases} == {"allow", "deny"}
    assert any(case.token == "" for case in cases)  # the unauthenticated case
    assert sum(1 for case in cases if case.expectation == "allow") == 1


def test_list_tools_returns_the_catalog_and_raises_when_it_cannot() -> None:
    catalog = {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "read_file"}]}}
    assert client_for(catalog).list_tools() == [{"name": "read_file"}]

    with pytest.raises(MCPError):
        client_for(rpc_error(-32020, "header mismatch"), status=400).list_tools()


def test_the_cli_requires_a_token_for_the_mcp_family() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["--target", "http://t.test", "--family", "mcp"])

    assert "client-credentials token" in str(caught.value)


def test_the_cli_runs_the_family_and_writes_a_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "mcp-report.json"

    def handler(request: httpx.Request) -> httpx.Response:
        if not request.headers.get("authorization"):
            return httpx.Response(401, json=rpc_error(-32001, "missing or malformed bearer token"))
        if request.headers.get("mcp-name") == "read_system_status":
            return httpx.Response(200, json=ok())
        return httpx.Response(200, json=tool_error("not on this agent's allowlist"))

    code = main(
        ["--target", "http://t.test", "--family", "mcp", "--token", "tok", "--report", str(report)],
        transport=httpx.MockTransport(handler),
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "family mcp" in out
    assert "findings 0" in out
    assert json.loads(report.read_text())["summary"]["cases"] == 10
