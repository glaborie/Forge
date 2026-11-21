from __future__ import annotations

import base64
import json
from pathlib import Path

from forge_audit import AuditLog
from forge_guard import ModelDetector, OutputGuard, find_pii, redact_pii

# Built at runtime: a literal test card and key-shaped string trip secret scanners.
CARD = " ".join(["4111"] + ["1111"] * 3)
BAD_CARD = " ".join(["4111"] + ["1111"] * 2 + ["1112"])
API_KEY = "sk-" + "proj-" + "a" * 24


def _segment(claims: dict[str, str]) -> str:
    raw = json.dumps(claims).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


JWT = ".".join([_segment({"alg": "HS256"}), _segment({"sub": "1"}), "a" * 24])
EMAIL = "alice@example.com"


def safety(*, block_at: float = 0.8, score: float = 0.9) -> ModelDetector:
    return ModelDetector(
        lambda text: ("unsafe", score), category="unsafe", owasp="LLM05", block_at=block_at
    )


def test_pii_is_redacted_and_the_value_is_gone() -> None:
    decision = OutputGuard().check(f"Contact {EMAIL} for details.")

    assert decision.action == "redact"
    assert decision.text == "Contact [REDACTED:email] for details."
    assert EMAIL not in decision.text


def test_a_valid_card_number_is_redacted() -> None:
    assert OutputGuard().check(f"card {CARD}").text == "card [REDACTED:credit_card]"


def test_a_number_that_fails_the_luhn_check_is_left_alone() -> None:
    """A bare pattern would redact order ids and timestamps."""
    decision = OutputGuard().check(f"order {BAD_CARD} shipped")

    assert decision.action == "allow"
    assert BAD_CARD in decision.text


def test_a_short_number_is_not_a_phone() -> None:
    assert OutputGuard().check("call 12345").action == "allow"


def test_only_configured_entities_are_redacted() -> None:
    guard = OutputGuard(entities=["email"])

    decision = guard.check(f"{EMAIL} card {CARD}")

    assert decision.text == f"[REDACTED:email] card {CARD}"


def test_an_unknown_entity_is_rejected() -> None:
    try:
        find_pii("x", ["passport"])
    except ValueError as exc:
        assert "passport" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unknown entity was accepted")


def test_an_api_key_and_a_jwt_are_redacted() -> None:
    decision = OutputGuard().check(f"key {API_KEY} and {JWT}")

    assert "[REDACTED:api_key]" in decision.text
    assert "[REDACTED:jwt]" in decision.text


def test_redaction_does_not_shift_later_spans() -> None:
    text = f"{EMAIL} then {EMAIL}"
    spans = find_pii(text)

    assert redact_pii(text, spans) == "[REDACTED:email] then [REDACTED:email]"


def test_pii_maps_to_llm02() -> None:
    assert OutputGuard().check(EMAIL).owasp == ("LLM02",)


def test_a_safety_block_withholds_the_text_and_outranks_redaction() -> None:
    decision = OutputGuard(safety=safety()).check(f"{EMAIL} and something dangerous")

    assert decision.action == "block"
    assert decision.text == ""
    assert "LLM05" in decision.owasp


def test_a_safety_flag_leaves_the_text_but_marks_it() -> None:
    decision = OutputGuard(safety=safety(block_at=0.99, score=0.9)).check("a mild concern")

    assert decision.action == "flag"
    assert decision.text == "a mild concern"


def test_redaction_can_be_disabled() -> None:
    decision = OutputGuard(redact=False).check(f"mail {EMAIL}")

    assert decision.action == "allow"
    assert EMAIL in decision.text


def test_a_redaction_is_audited(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")

    OutputGuard(audit=log).check(f"{EMAIL} card {CARD}", request_id="r-1", tenant_id="t-1")

    records = [json.loads(line) for line in (tmp_path / "audit.jsonl").read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["policy"] == "guardrail.output.v1"
    assert records[0]["action"] == "redact"
    assert records[0]["reason"] == "credit_card,email"
    assert records[0]["request_id"] == "r-1"
    assert records[0]["tenant_id"] == "t-1"
    assert log.verify() is None


def test_an_allowed_output_is_not_audited(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")

    OutputGuard(audit=log).check("nothing to see here")

    assert (tmp_path / "audit.jsonl").read_text() == ""


def test_the_audit_log_keeps_a_hash_not_the_pii(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")

    OutputGuard(audit=log).check(f"{EMAIL} {CARD}")

    text = (tmp_path / "audit.jsonl").read_text()
    assert EMAIL not in text
    assert "4111" not in text
