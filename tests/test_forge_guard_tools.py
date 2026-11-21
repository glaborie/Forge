from __future__ import annotations

import json
from pathlib import Path

from forge_audit import AuditLog
from forge_guard import ToolGrants, ToolPolicy


def grants() -> ToolGrants:
    return ToolGrants(
        {
            "analyst": ToolPolicy(allow=frozenset({"read_file", "read_system_status"})),
            "operator": ToolPolicy(
                allow=frozenset({"read_file", "execute_file_write"}),
                deny=frozenset({"execute_file_write"}),
            ),
        }
    )


def test_a_tool_in_the_allowlist_is_allowed() -> None:
    decision = grants().authorize("analyst", "read_file")

    assert decision.allowed
    assert decision.reason == "allowed"


def test_a_tool_outside_the_allowlist_is_denied() -> None:
    decision = grants().authorize("analyst", "execute_file_write")

    assert not decision.allowed
    assert decision.reason == "not_in_allowlist"


def test_an_explicit_deny_wins_over_the_allowlist() -> None:
    decision = grants().authorize("operator", "execute_file_write")

    assert not decision.allowed
    assert decision.reason == "explicitly_denied"


def test_an_agent_without_a_policy_gets_nothing() -> None:
    """A missing entry is a configuration mistake, not a licence."""
    decision = grants().authorize("ghost", "read_file")

    assert not decision.allowed
    assert decision.reason == "not_in_allowlist"


def test_an_allowlist_of_none_allows_everything_not_denied() -> None:
    permissive = ToolGrants({"svc": ToolPolicy()})

    assert permissive.authorize("svc", "anything").allowed


def test_a_denied_call_is_logged_as_a_block(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")

    decision = grants().authorize(
        "analyst",
        "execute_file_write",
        arguments='{"path": "/etc/shadow"}',
        audit=log,
        request_id="req-1",
        tenant_id="t-1",
    )

    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert not decision.allowed
    assert len(records) == 1
    assert records[0]["policy"] == "guardrail.tool.v1"
    assert records[0]["action"] == "block"
    assert records[0]["reason"] == "not_in_allowlist"
    assert records[0]["request_id"] == "req-1"
    assert records[0]["tenant_id"] == "t-1"
    assert log.verify() is None


def test_an_allowed_call_leaves_no_record(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")

    grants().authorize("analyst", "read_file", audit=log)

    assert (tmp_path / "audit.jsonl").read_text() == ""


def test_arguments_are_hashed_and_never_stored(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")

    grants().authorize("analyst", "execute_file_write", arguments="super-secret-path", audit=log)

    text = (tmp_path / "audit.jsonl").read_text()
    assert "super-secret-path" not in text
    assert "execute_file_write" not in text


def test_the_decision_maps_to_owasp_llm06() -> None:
    assert grants().authorize("analyst", "nmap").owasp == "LLM06"
