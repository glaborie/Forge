"""The CI gate: adversarial cases must be detected, and a regression must fail the build.

This runs the corpus against two mock targets. The vulnerable one complies; the
defensive one blocks. If Forge stops noticing a case that the vulnerable target
gave away, the first set fails — which is the only property that makes an
"adversarial tests in CI" claim worth anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from forge_harness import Runner, Target, load_corpus

CORPUS = Path(__file__).resolve().parents[1] / "harness" / "corpus" / "injection.json"
CANARIES = (
    "OWNED",
    "ZQ7-CANARY",
    "RT9-CANARY",
    "KM4-CANARY",
    "JB1-OK",
    "alice@example.com",
    "TOOL-CALL-OK",
)
CATEGORIES = {"injection", "jailbreak", "extraction", "obfuscation", "pii", "tool"}


def prompt_of(request: httpx.Request) -> str:
    body: dict[str, Any] = json.loads(request.content)
    return " ".join(str(message.get("content") or "") for message in body.get("messages", []))


def vulnerable(request: httpx.Request) -> httpx.Response:
    """Complies: echoes the canary it was asked for, otherwise just answers."""
    text = prompt_of(request)
    echo = next(
        (canary for canary in CANARIES if canary in text), "Sure — here is a helpful answer."
    )
    return httpx.Response(
        200, json={"choices": [{"index": 0, "message": {"content": echo}, "finish_reason": "stop"}]}
    )


def defensive(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {"index": 0, "message": {"content": ""}, "finish_reason": "content_filter"}
            ],
            "bastion": {"blocked": True},
        },
    )


def run_against(transport: httpx.MockTransport) -> Any:
    return Runner().run(
        load_corpus(CORPUS), Target("http://t.test", model="m", transport=transport)
    )


def test_at_least_five_attack_categories_are_covered() -> None:
    tags = {tag for case in load_corpus(CORPUS) for tag in case.tags}

    assert len(CATEGORIES & tags) >= 5
    assert CATEGORIES <= tags


def test_every_case_declares_a_severity_and_an_owasp_risk() -> None:
    for case in load_corpus(CORPUS):
        assert case.severity in {"critical", "high", "medium", "low"}
        assert case.owasp.startswith("LLM")


def test_a_complying_target_is_fully_detected() -> None:
    run = run_against(httpx.MockTransport(vulnerable))

    findings = run.findings()
    attack_cases = [case for case in load_corpus(CORPUS) if case.expectation != "answer"]

    assert {finding.case_id for finding in findings} == {case.id for case in attack_cases}


def test_findings_are_ranked_by_severity() -> None:
    findings = run_against(httpx.MockTransport(vulnerable)).findings()

    assert findings[0].severity == "critical"
    assert [finding.rank for finding in findings] == sorted(finding.rank for finding in findings)


def test_every_finding_is_linked_to_an_owasp_risk() -> None:
    findings = run_against(httpx.MockTransport(vulnerable)).findings()

    assert {finding.owasp for finding in findings} >= {"LLM01", "LLM02", "LLM06", "LLM07"}


def test_a_defending_target_produces_no_findings() -> None:
    run = run_against(httpx.MockTransport(defensive))

    assert run.findings() == []
    assert run.summary()["by_severity"] == {}


def test_the_benign_control_is_never_a_finding() -> None:
    benign = [finding for finding in run_against(httpx.MockTransport(vulnerable)).findings()]

    assert "benign-001" not in {finding.case_id for finding in benign}


def test_a_regression_in_detection_would_fail_this_suite() -> None:
    """If the harness stopped labelling a canary echo, the CI gate must notice."""
    run = Runner().run(
        load_corpus(CORPUS),
        Target("http://t.test", model="m", transport=httpx.MockTransport(vulnerable)),
    )

    quiet = Runner().run(
        [case for case in load_corpus(CORPUS) if case.expectation != "answer"],
        Target("http://t.test", model="m", transport=httpx.MockTransport(defensive)),
    )

    assert run.summary()["by_severity"] != {}
    assert quiet.summary()["by_severity"] == {}
