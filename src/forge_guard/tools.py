"""Authorize a tool call before it runs.

This is the one place in `forge_guard` that is an enforcement point rather than
an observation: a denied call must not execute. It still leaves evidence, so a
refusal is a record and not a silent drop. Maps to OWASP LLM06, excessive
agency — the model choosing an action the caller was never granted.

The default is deny: an agent with no entry gets nothing, because a missing
policy is a configuration mistake and not a licence.
"""

from __future__ import annotations

from dataclasses import dataclass

from forge_audit import AuditLog

OWASP = "LLM06"


@dataclass(frozen=True)
class ToolPolicy:
    """Allowlist, denylist, or both. A deny entry always wins."""

    allow: frozenset[str] | None = None
    deny: frozenset[str] = frozenset()

    def check(self, tool: str) -> tuple[bool, str]:
        if tool in self.deny:
            return False, "explicitly_denied"
        if self.allow is not None and tool not in self.allow:
            return False, "not_in_allowlist"
        return True, "allowed"


@dataclass(frozen=True)
class Authorization:
    allowed: bool
    reason: str
    agent: str
    tool: str
    owasp: str = OWASP


class ToolGrants:
    """Per-agent tool policy; anything not granted a policy is refused."""

    def __init__(
        self,
        grants: dict[str, ToolPolicy] | None = None,
        *,
        default: ToolPolicy | None = None,
    ) -> None:
        self.grants = dict(grants or {})
        # No policy means no tools: fail closed.
        self.default = default if default is not None else ToolPolicy(allow=frozenset())

    def authorize(
        self,
        agent: str,
        tool: str,
        *,
        arguments: str = "",
        audit: AuditLog | None = None,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> Authorization:
        policy = self.grants.get(agent, self.default)
        allowed, reason = policy.check(tool)
        decision = Authorization(allowed=allowed, reason=reason, agent=agent, tool=tool)
        if not allowed and audit is not None:
            # Written before the caller decides to run anything: the argument
            # text is hashed by AuditLog and never stored.
            audit.record(
                input_text=f"{agent}\0{tool}\0{arguments}",
                policy="guardrail.tool.v1",
                action="block",
                reason=reason,
                request_id=request_id,
                tenant_id=tenant_id,
            )
        return decision
