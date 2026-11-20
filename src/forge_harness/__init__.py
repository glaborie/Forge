"""Inject labelled cases into a target and record both sides of the exchange.

Forge does not protect the target: the payloads are the test. This package posts
each case, labels the input with `forge_guard` detectors, labels the response
with the output detectors, and writes both halves to the audit log. Scoring is
H2; this is the transport and the evidence.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from forge_audit import AuditLog
from forge_guard import OUTPUT_RULES, ModelDetector, Normalized, RegexDetector, normalize

type Detector = RegexDetector | ModelDetector


@dataclass(frozen=True)
class Case:
    """One test input and what a compliant target should do with it."""

    id: str
    prompt: str
    expectation: str = "refuse"
    tags: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Case:
        return cls(
            id=str(data["id"]),
            prompt=str(data["prompt"]),
            expectation=str(data.get("expectation", "refuse")),
            tags=tuple(data.get("tags", ())),
        )


@dataclass(frozen=True)
class Reply:
    status: int
    text: str
    latency_ms: float


@dataclass(frozen=True)
class Record:
    case_id: str
    expectation: str
    status: int
    latency_ms: float
    input_labels: tuple[str, ...]
    response_labels: tuple[str, ...]
    input_hash: str
    response_hash: str

    @property
    def leaked(self) -> bool:
        """A response that itself reads like a system-prompt leak."""
        return any(label.startswith("LLM07") for label in self.response_labels)


@dataclass
class Run:
    records: list[Record] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        by_expectation: dict[str, int] = {}
        for record in self.records:
            by_expectation[record.expectation] = by_expectation.get(record.expectation, 0) + 1
        return {
            "cases": len(self.records),
            "by_expectation": by_expectation,
            "labelled_leaks": sum(1 for r in self.records if r.leaked),
            "errors": sum(1 for r in self.records if r.status >= 400 or r.status == 0),
        }

    def to_json(self, path: str | Path | None = None) -> str:
        payload = json.dumps([asdict(record) for record in self.records], indent=2)
        if path is not None:
            Path(path).write_text(payload + "\n", encoding="utf-8")
        return payload


class Target:
    """An OpenAI-compatible endpoint under test."""

    def __init__(
        self,
        base_url: str,
        *,
        path: str = "/v1/chat/completions",
        model: str = "target",
        timeout: float = 30.0,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.path = path
        self.model = model
        # Targets commonly require a bearer token the OpenAPI spec may not declare.
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport, headers=headers
        )

    def send(self, prompt: str) -> Reply:
        started = time.monotonic()
        body = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        try:
            response = self.client.post(self.path, json=body)
            status = response.status_code
            text = _response_text(response)
        except httpx.HTTPError as exc:
            # A dead target is a result, not a crash: record it and move on.
            status, text = 0, f"transport error: {exc}"
        return Reply(status=status, text=text, latency_ms=(time.monotonic() - started) * 1000)


class Runner:
    """Sends cases and records what was asked and what came back."""

    def __init__(
        self,
        *,
        audit: AuditLog | None = None,
        input_detectors: list[Detector] | None = None,
        output_detectors: list[Detector] | None = None,
    ) -> None:
        self.audit = audit
        self.input_detectors = input_detectors or [RegexDetector()]
        # Outputs are judged with leak-shaped rules, not the request-shaped ones.
        self.output_detectors = output_detectors or [RegexDetector(OUTPUT_RULES)]

    def run(self, cases: list[Case], target: Target) -> Run:
        run = Run()
        for case in cases:
            input_labels = self._labels(case.prompt, self.input_detectors)
            reply = target.send(case.prompt)
            output_labels = self._labels(reply.text, self.output_detectors)

            record = Record(
                case_id=case.id,
                expectation=case.expectation,
                status=reply.status,
                latency_ms=round(reply.latency_ms, 1),
                input_labels=input_labels,
                response_labels=output_labels,
                input_hash=_hash(case.prompt),
                response_hash=_hash(reply.text),
            )
            run.records.append(record)
            self._record(record, case.prompt, reply.text)
        return run

    def _labels(self, text: str, detectors: list[Detector]) -> tuple[str, ...]:
        normalized: Normalized = normalize(text)
        labels = {
            f"{finding.owasp}:{finding.category}"
            for detector in detectors
            for finding in detector.detect(normalized)
        }
        return tuple(sorted(labels))

    def _record(self, record: Record, prompt: str, response: str) -> None:
        if self.audit is None:
            return
        reasons = ",".join(label.split(":", 1)[1] for label in record.input_labels) or "none"
        self.audit.record(
            input_text=prompt,
            policy="harness.input",
            action="log",
            reason=reasons,
            request_id=record.case_id,
        )
        self.audit.record(
            input_text=response,
            policy="harness.output",
            action="log",
            reason=",".join(label.split(":", 1)[1] for label in record.response_labels) or "none",
            request_id=record.case_id,
        )


def _response_text(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        return json.dumps(data)[:2000]


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_corpus(path: str | Path) -> list[Case]:
    """Read a corpus: a JSON array, or one `{id, prompt, expectation, tags}` per line."""
    text = Path(path).read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        return [Case.from_dict(item) for item in json.loads(text)]
    cases = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            try:
                cases.append(Case.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
    return cases
