from __future__ import annotations

import json
from typing import Any

import httpx

from forge_harness import Case, Target, load_corpus
from forge_harness.actions import (
    ABSENT_TICKET,
    BASELINE_EVENTS,
    ApprovalGate,
    Ticket,
    classify,
    probe_gate,
    run_actions,
)


def gate_with(handler: Any) -> ApprovalGate:
    return ApprovalGate("http://t.test", token="tok", transport=httpx.MockTransport(handler))


def answering(text: str, conversation: str = "conv-1") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "conversation_id": conversation,
                "message": {"role": "assistant", "content": text},
                "blocked": False,
            },
        )

    return httpx.MockTransport(handler)


def test_tickets_are_read_from_the_approvals_envelope() -> None:
    gate = gate_with(
        lambda request: httpx.Response(
            200, json={"approvals": [{"id": "t-1", "status": "pending"}], "count": 1}
        )
    )

    tickets = gate.tickets()

    assert [ticket.id for ticket in tickets] == ["t-1"]
    assert tickets[0].raw["status"] == "pending"


def test_a_bare_list_of_tickets_is_accepted() -> None:
    gate = gate_with(lambda request: httpx.Response(200, json=[{"id": "t-2"}]))

    assert [ticket.id for ticket in gate.tickets()] == ["t-2"]


def test_decide_is_form_encoded() -> None:
    """The endpoint refuses a JSON body, so the encoding is load-bearing."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404, json={"detail": "approval ticket not found"})

    assert gate_with(handler).decide("t-1", "approve") == 404
    assert seen[0].headers["content-type"] == "application/x-www-form-urlencoded"
    assert seen[0].content == b"action=approve"


def test_decide_without_an_action_sends_an_empty_body() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(422, json={"detail": "missing"})

    gate_with(handler).decide("t-1", None)

    assert b"action" not in seen[0].content


def test_classify_gated_when_a_ticket_names_the_conversation() -> None:
    tickets = [Ticket("t-1", {"id": "t-1", "conversation_id": "conv-9"})]

    assert classify(status=200, session_id="conv-9", tickets=tickets, events=[]) == "gated"


def test_classify_executed_on_an_unexpected_event() -> None:
    assert (
        classify(
            status=200,
            session_id="conv-1",
            tickets=[],
            events=[{"event_type": "TOOL_EXECUTED"}],
        )
        == "executed"
    )


def test_classify_no_action_on_the_ordinary_lifecycle() -> None:
    events = [{"event_type": name} for name in sorted(BASELINE_EVENTS)]

    assert classify(status=200, session_id="conv-1", tickets=[], events=events) == "no-action"


def test_classify_error_beats_everything() -> None:
    assert classify(status=500, session_id="conv-1", tickets=[], events=[]) == "error"


def test_run_actions_marks_a_gated_case_and_closes_the_ticket() -> None:
    decisions: list[bytes] = []
    snapshots = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal snapshots
        if request.url.path == "/api/approvals" and request.method == "GET":
            # Empty before the run; the case creates the ticket.
            snapshots += 1
            tickets = [] if snapshots == 1 else [{"id": "t-new", "conversation_id": "conv-1"}]
            return httpx.Response(200, json={"approvals": tickets})
        if request.url.path == "/api/audit":
            return httpx.Response(200, json={"records": []})
        decisions.append(request.content)
        return httpx.Response(200, json={"status": "rejected"})

    gate = gate_with(handler)
    target = Target("http://t.test", path="/v1/chat", send_model=False, transport=answering("done"))
    run = run_actions([Case(id="a1", prompt="write a file")], target, gate)

    assert run.records[0].verdict == "gated"
    assert decisions == [b"action=reject"]
    assert run.notes["created_tickets"] == 1


def test_run_actions_leaves_preexisting_tickets_alone() -> None:
    decisions: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/approvals":
            return httpx.Response(
                200, json={"approvals": [{"id": "t-old", "conversation_id": "other"}]}
            )
        if request.url.path == "/api/audit":
            return httpx.Response(200, json={"records": []})
        decisions.append(request.content)
        return httpx.Response(200, json={})

    gate = gate_with(handler)
    target = Target("http://t.test", path="/v1/chat", send_model=False, transport=answering("ok"))
    run = run_actions([Case(id="a1", prompt="hi")], target, gate)

    assert run.records[0].verdict == "no-action"
    assert decisions == []
    assert run.notes["created_tickets"] == 0


def test_probe_gate_reports_matching_and_mismatched_expectations() -> None:
    def allowed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "approval ticket not found"})

    def denied(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/action") and request.content == b"action=approvee":
            return httpx.Response(400, json={"detail": "action must be approve or reject"})
        if request.url.path.endswith("/action") and request.content == b"":
            return httpx.Response(422, json={"detail": "missing"})
        return httpx.Response(403, json={"detail": "insufficient role"})

    checks = probe_gate(
        {"admin": gate_with(allowed), "readonly": gate_with(denied)}, may_decide={"admin"}
    )
    verdicts = {(check.name, check.role): check.verdict for check in checks}

    assert verdicts[("decide-unknown-ticket", "admin")] == "as-expected"
    assert verdicts[("decide-unknown-ticket", "readonly")] == "as-expected"
    assert all(check.status for check in checks)


def test_probe_gate_flags_a_role_that_should_have_been_denied() -> None:
    leaky = gate_with(lambda request: httpx.Response(404, json={"detail": "ticket not found"}))

    checks = probe_gate({"readonly": leaky}, may_decide={"admin"})

    assert [check.verdict for check in checks if check.name == "decide-unknown-ticket"] == [
        "finding"
    ]


def test_the_action_corpus_loads() -> None:
    cases = load_corpus("harness/corpus/actions.json")

    assert [case.id for case in cases] == [
        "action-001-file-write",
        "action-002-truncate-ledger",
        "action-003-self-approve",
    ]
    assert all(case.expectation == "no-action" for case in cases)


def test_absent_ticket_is_a_valid_uuid() -> None:
    assert len(ABSENT_TICKET) == 36
    assert json.dumps({"id": ABSENT_TICKET})
