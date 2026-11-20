"""Input guardrails for prompt injection and system-prompt leakage.

Built from the OWASP *LLM Prompt Injection Prevention* cheat sheet. The single
most important sentence in that document is that input screening is **not a
security boundary** — LLMs do not separate instructions from data, and a deny
list can be rephrased around. Treat a decision here as a signal for logging,
rate limiting and review, and enforce permissions at the tool boundary.

Two deliberate choices follow from it:

* Rules match **phrases**, not single words. `delete` or `system` on their own
  appear in benign requests; flagging them blocks real users.
* The default action is **observe**, not block. Forge stress-tests target systems
  with adversarial input; a guard that blocked the payload would stop the test
  from happening. Enforcement is opt-in via `policy={...}`.
* Screened text is a *copy*. Normalisation is applied for matching only, never
  to what gets forwarded to the model, and anything normalisation had to change
  is reported so a human can look at it.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from forge_audit import AuditLog

Action = Literal["allow", "log", "flag", "block"]
Severity = {"allow": 0, "log": 1, "flag": 2, "block": 3}

MAX_INPUT_CHARS = 8_000
_ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"
_TAG_RANGE = (0xE0000, 0xE007F)
_BASE64_CANDIDATE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")
_HEX_CANDIDATE = re.compile(r"(?:[0-9a-fA-F]{2}){8,}")


@dataclass(frozen=True)
class Rule:
    """One phrase-level pattern and the OWASP risk it maps to."""

    name: str
    pattern: re.Pattern[str]
    category: str
    owasp: str
    action: Action = "block"
    description: str = ""


def _rule(name: str, pattern: str, category: str, owasp: str, action: Action = "block") -> Rule:
    return Rule(name, re.compile(pattern, re.IGNORECASE), category, owasp, action)


# Phrase-level, deriving from the cheat sheet's attack catalogue. Deliberately
# narrow: a missed paraphrase is cheaper than blocking "how do I delete my account".
DEFAULT_RULES: tuple[Rule, ...] = (
    _rule(
        "ignore_instructions",
        r"\b(ignore|disregard|forget)\s+(all\s+|any\s+)?(the\s+|your\s+)?"
        r"(previous|prior|above|earlier|preceding)\s+(instruction|instruction set|prompt|rule)s?",
        "prompt_injection",
        "LLM01",
    ),
    _rule(
        "override_instructions",
        r"\b(ignore|disregard)\s+(all\s+)?(the\s+)?(above|everything)\b.{0,20}\b"
        r"(instructions?|rules?|context)\b",
        "prompt_injection",
        "LLM01",
    ),
    _rule(
        "developer_mode",
        r"\byou\s+are\s+now\s+(in\s+)?(developer|debug|god|dan|jailbreak)\s*mode\b",
        "jailbreak",
        "LLM01",
    ),
    _rule(
        "persona_override",
        r"\b(pretend|act)\s+(to\s+be|as\s+if\s+you\s+are)\s+(an?\s+)?"
        r"(unrestricted|unfiltered|uncensored|evil)",
        "jailbreak",
        "LLM01",
    ),
    _rule("dan_jailbreak", r"\b(do anything now|dan mode|jailbreak mode)\b", "jailbreak", "LLM01"),
    _rule(
        "reveal_system_prompt",
        r"\b(reveal|show|print|output|repeat|tell\s+me)\s+(me\s+)?(your\s+|the\s+)?"
        r"(system\s+prompt|system\s+instructions|hidden\s+instructions|initial\s+prompt)\b",
        "system_prompt_leak",
        "LLM07",
    ),
    _rule(
        "repeat_above",
        r"\b(repeat|print|output)\s+(the\s+)?(text|content|instructions|words)\s+above\b",
        "system_prompt_leak",
        "LLM07",
    ),
    _rule(
        "exact_instructions",
        r"\bwhat\s+(were|are)\s+your\s+(exact\s+)?(instructions|system\s+prompt|rules)\b",
        "system_prompt_leak",
        "LLM07",
    ),
)


# Output-side rules: what a leaked system prompt looks like coming back, rather
# than a request for one. D2 extends this with PII.
OUTPUT_RULES: tuple[Rule, ...] = (
    _rule(
        "leaked_system_prompt",
        r"\bmy\s+(system\s+)?(prompt|instructions)\s+(says|are|is)\b",
        "system_prompt_leak",
        "LLM07",
    ),
    _rule(
        "preamble_leak",
        r"\byou\s+are\s+(a|an)\s+[a-z\s]{0,40}(assistant|ai|model)\b",
        "system_prompt_leak",
        "LLM07",
    ),
    _rule(
        "labelled_instructions",
        r"(?m)^\s*(system|instructions)\s*:",
        "system_prompt_leak",
        "LLM07",
    ),
)


@dataclass
class Normalized:
    """A screened copy of the input, plus what screening had to change."""

    original: str
    screened: str
    flags: list[str] = field(default_factory=list)
    decoded: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return len(self.original) > MAX_INPUT_CHARS


@dataclass(frozen=True)
class Finding:
    rule: str
    category: str
    owasp: str
    action: Action
    detail: str = ""


@dataclass(frozen=True)
class Decision:
    action: Action
    findings: tuple[Finding, ...]
    normalized: Normalized

    @property
    def blocked(self) -> bool:
        return self.action == "block"

    @property
    def owasp(self) -> tuple[str, ...]:
        return tuple(sorted({finding.owasp for finding in self.findings}))


def normalize(text: str) -> Normalized:
    """Produce a matching copy. Never mutate what the caller forwards."""
    flags: list[str] = []
    decoded: list[str] = []

    if len(text) > MAX_INPUT_CHARS:
        flags.append("input_truncated")

    screened = unicodedata.normalize("NFKC", text[:MAX_INPUT_CHARS])
    if screened != text[:MAX_INPUT_CHARS]:
        flags.append("nfkc_changed")

    cleaned = []
    for char in screened:
        code = ord(char)
        if char in _ZERO_WIDTH or _TAG_RANGE[0] <= code <= _TAG_RANGE[1]:
            flags.append("invisible_characters")
            continue
        cleaned.append(char)
    screened = "".join(cleaned)

    for candidate in _BASE64_CANDIDATE.findall(text):
        try:
            raw = base64.b64decode(candidate + "=" * (-len(candidate) % 4), validate=True)
        except (binascii.Error, ValueError):
            continue
        if decoded_text := _printable(raw):
            decoded.append(decoded_text)
            flags.append("encoded_payload")

    for candidate in _HEX_CANDIDATE.findall(text):
        if decoded_text := _printable(bytes.fromhex(candidate)):
            decoded.append(decoded_text)
            flags.append("encoded_payload")

    if decoded:
        # Decoded payloads are inspected, never forwarded.
        screened = screened + "\n" + "\n".join(decoded)

    return Normalized(text, screened, sorted(set(flags)), decoded)


def _printable(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(text) < 8 or not text.isprintable():
        return None
    return text


class RegexDetector:
    """Phrase-level matching over normalised text."""

    def __init__(self, rules: Iterable[Rule] = DEFAULT_RULES) -> None:
        self.rules = tuple(rules)

    def detect(self, normalized: Normalized) -> list[Finding]:
        findings = []
        for rule in self.rules:
            match = rule.pattern.search(normalized.screened)
            if match:
                findings.append(
                    Finding(rule.name, rule.category, rule.owasp, rule.action, match.group(0))
                )
        return findings


Classifier = Callable[[str], tuple[str, float]]


class ClassifierUnavailable(RuntimeError):
    """The classifier produced no verdict. `ModelDetector` turns this into a flag."""


class ModelDetector:
    """Adapter for a classifier supplied by the deployment.

    The callable returns `(category, score)` where score is 0–1. Nothing here
    picks a model: the agent already talks to an OpenAI-compatible endpoint, and
    naming one in this package would be a dependency the caller did not ask for.
    """

    def __init__(
        self,
        classify: Classifier,
        *,
        category: str = "prompt_injection",
        owasp: str = "LLM01",
        block_at: float = 0.8,
        flag_at: float = 0.5,
    ) -> None:
        self.classify = classify
        self.category = category
        self.owasp = owasp
        self.block_at = block_at
        self.flag_at = flag_at

    def detect(self, normalized: Normalized) -> list[Finding]:
        try:
            category, score = self.classify(normalized.screened)
        except Exception as exc:  # noqa: BLE001 - a missing verdict must not pass traffic
            return [
                Finding("classifier_error", "classifier_error", self.owasp, "flag", str(exc)[:200])
            ]
        if score < self.flag_at:
            return []
        action: Action = "block" if score >= self.block_at else "flag"
        return [
            Finding(
                f"classifier:{category}",
                category or self.category,
                self.owasp,
                action,
                f"score={score:.2f}",
            )
        ]


class Guard:
    """Runs detectors, applies policy, records the decision, queues flags."""

    def __init__(
        self,
        *,
        detectors: Iterable[RegexDetector | ModelDetector] | None = None,
        audit: AuditLog | None = None,
        review_queue: str | Path | None = None,
        policy: dict[str, Action] | None = None,
    ) -> None:
        self.detectors = tuple(detectors) if detectors is not None else (RegexDetector(),)
        self.audit = audit
        self.review_queue = Path(review_queue) if review_queue else None
        if self.review_queue:
            self.review_queue.parent.mkdir(parents=True, exist_ok=True)
        # Observe by default: these payloads are the point of the harness. A
        # caller that wants enforcement passes policy={"prompt_injection": "block"}.
        self.policy: dict[str, Action] = {
            "prompt_injection": "log",
            "jailbreak": "log",
            "system_prompt_leak": "log",
            "obfuscation": "flag",
            **(policy or {}),
        }

    def check(
        self,
        text: str,
        *,
        request_id: str | None = None,
        tenant_id: str | None = None,
    ) -> Decision:
        normalized = normalize(text)
        findings = [f for detector in self.detectors for f in detector.detect(normalized)]

        for flag in normalized.flags:
            finding = self._flag_finding(flag)
            if finding:
                findings.append(finding)

        actions: list[Action] = [self.policy.get(f.category, f.action) for f in findings]
        action: Action = max(actions, key=lambda a: Severity[a]) if actions else "allow"
        decision = Decision(action, tuple(findings), normalized)

        if self.audit is not None and action != "allow":
            self.audit.record(
                input_text=text,
                policy=f"guard.input:{','.join(sorted({f.rule for f in findings}))}",
                action=action,
                reason=",".join(sorted({f.category for f in findings})),
                request_id=request_id,
                tenant_id=tenant_id,
            )
        if action == "flag" and self.review_queue is not None:
            self.review_queue.open("a", encoding="utf-8").write(
                f'{{"request_id": "{request_id or ""}", "reasons": "'
                f'{",".join(sorted({f.category for f in findings}))}"}}\n'
            )
        return decision

    def _flag_finding(self, flag: str) -> Finding | None:
        if flag == "invisible_characters":
            return Finding(
                "invisible_characters",
                "obfuscation",
                "LLM01",
                "flag",
                "zero-width or tag characters",
            )
        if flag == "encoded_payload":
            return Finding(
                "encoded_payload", "obfuscation", "LLM01", "flag", "base64 or hex content"
            )
        if flag == "input_truncated":
            return Finding("input_truncated", "abuse", "LLM10", "flag", "input over the size cap")
        return None
