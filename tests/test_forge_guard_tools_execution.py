"""Prove the authorization check actually gates execution, not just reports.

`ToolGrants` is a library, so the only way a denial can be trusted is if a caller
that consults it refuses to act. This stub executor is that caller: it executes
only when `authorize()` says so, which is the property D4 claims.
"""

from __future__ import annotations

import json
from pathlib import Path

from forge_audit import AuditLog
from forge_guard import ToolGrants, ToolPolicy


class StubExecutor:
    """A tool runtime that executes only what the grants allow."""

    def __init__(self, grants: ToolGrants, audit: AuditLog | None = None) -> None:
        self.grants = grants
        self.audit = audit
        self.effects: list[str] = []

    def run(self, agent: str, tool: str, arguments: str = "") -> bool:
        decision = self.grants.authorize(agent, tool, arguments=arguments, audit=self.audit)
        if not decision.allowed:
            return False
        self.effects.append(tool)
        return True


def grants() -> ToolGrants:
    return ToolGrants(
        {
            "analyst": ToolPolicy(allow=frozenset({"read_file"})),
            "operator": ToolPolicy(allow=frozenset({"read_file", "execute_file_write"})),
        }
    )


def test_a_denied_tool_leaves_no_side_effect(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    executor = StubExecutor(grants(), audit=log)

    ran = executor.run("analyst", "execute_file_write", '{"path": "/etc/passwd"}')

    assert not ran
    assert executor.effects == []


def test_a_denial_is_recorded_even_though_nothing_ran(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    executor = StubExecutor(grants(), audit=log)

    executor.run("analyst", "execute_file_write")

    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert [r["action"] for r in records] == ["block"]
    assert [r["reason"] for r in records] == ["not_in_allowlist"]
    assert executor.effects == []


def test_an_allowed_tool_runs_exactly_once(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    executor = StubExecutor(grants(), audit=log)

    assert executor.run("operator", "execute_file_write")
    assert executor.effects == ["execute_file_write"]
    assert (tmp_path / "audit.jsonl").read_text() == ""


def test_an_unknown_agent_cannot_execute_anything(tmp_path: Path) -> None:
    executor = StubExecutor(grants())

    assert not executor.run("ghost", "read_file")
    assert executor.effects == []
