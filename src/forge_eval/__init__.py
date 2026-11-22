"""LLM-as-judge evaluation: rubrics in, one score per trace out.

The judge is a caller-supplied `ask(prompt) -> text` callable, the same shape
`ModelDetector` uses for its classifier: no model is bundled here, because the
deployment picks the model and the agent already talks to an OpenAI-compatible
endpoint. `forge_eval.openrouter.ask` is the adapter for that.

Scoring direction is uniform: **1.0 means the criteria are fully satisfied**, so
`hallucination` is scored as groundedness. Mixing directions across metrics makes
every aggregate meaningless, and an aggregate is why the scores are stored.

Every score carries a `version` derived from the model, the rubric and the prompt
template. Editing a rubric therefore produces a different version rather than a
silently incomparable number, which is the difference between an evaluation and a
pile of floats.

A judge that cannot answer raises `JudgeError`. It never scores 0.0: a fabricated
zero looks like a failed answer, not a failed evaluator.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from opentelemetry import trace


class JudgeError(RuntimeError):
    """The judge could not produce a usable score."""


@dataclass(frozen=True)
class Rubric:
    """What a good answer looks like for one use case.

    `reference=True` means the rubric compares the answer against an expected
    answer; `reference=False` judges the answer on its own (plus `context` when
    the sample carries it).
    """

    name: str
    criteria: str
    reference: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise JudgeError("a rubric needs a name")
        if not self.criteria.strip():
            raise JudgeError(f"rubric {self.name!r} has no criteria")


@dataclass
class Sample:
    """One answer to judge. `expected` is required only by a reference-based rubric."""

    input: str
    output: str
    expected: str = ""
    context: str = ""


@dataclass(frozen=True)
class Score:
    metric: str
    value: float
    reason: str
    trace_id: str
    version: str
    mode: str
    at: str


PROMPT = """You are evaluating one answer from an AI system.

Criteria for {name}: {criteria}
Score 1.0 when the answer fully satisfies the criteria, 0.0 when it does not at all.

Input:
{input}

Answer:
{output}
{extra}
Reply with JSON only, no prose: {{"score": <number from 0 to 1>, "reason": "<one sentence>"}}"""


RUBRICS: dict[str, Rubric] = {
    "hallucination": Rubric(
        "hallucination",
        "The answer states only what the reference answer supports; any invented "
        "fact, figure or citation lowers the score.",
        reference=True,
    ),
    "faithfulness": Rubric(
        "faithfulness",
        "Every claim in the answer is supported by the supplied context; claims "
        "outside it lower the score.",
    ),
    "relevance": Rubric(
        "relevance",
        "The answer addresses the question actually asked, without drifting to "
        "adjacent topics or padding.",
    ),
    "context_recall": Rubric(
        "context_recall",
        "The answer covers every point of the reference answer that the question required.",
        reference=True,
    ),
}


def build_prompt(rubric: Rubric, sample: Sample) -> str:
    extra = ""
    if sample.context.strip():
        extra += f"\nContext:\n{sample.context.strip()}\n"
    if rubric.reference:
        extra += f"\nReference answer:\n{sample.expected.strip()}\n"
    return PROMPT.format(
        name=rubric.name,
        criteria=rubric.criteria.strip(),
        input=sample.input.strip(),
        output=sample.output.strip(),
        extra=extra,
    )


def current_trace_id() -> str:
    """The active span's trace id, or "" when nothing is being traced."""
    context = trace.get_current_span().get_span_context()
    return format(context.trace_id, "032x") if context.is_valid else ""


def unfence(content: str) -> str:
    """Judges wrap JSON in a fenced block despite the instruction often enough to matter."""
    text = content.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        text = text.removeprefix("json").strip()
    return text


@dataclass
class Evaluator:
    ask: Callable[[str], str]
    rubric: Rubric
    model: str = ""
    version: str = ""

    def evaluate(
        self,
        sample: Sample,
        *,
        rubric: Rubric | None = None,
        trace_id: str | None = None,
        store: ScoreStore | None = None,
    ) -> Score:
        effective = rubric or self.rubric
        if effective.reference and not sample.expected.strip():
            raise JudgeError(
                f"rubric {effective.name!r} is reference-based but the sample has no expected answer"
            )

        value, reason = self._parse(self.ask(build_prompt(effective, sample)))
        score = Score(
            metric=effective.name,
            value=value,
            reason=reason,
            trace_id=current_trace_id() if trace_id is None else trace_id,
            version=self._version(effective),
            mode="reference-based" if effective.reference else "reference-free",
            at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        if store is not None:
            store.append(score)
        return score

    def _version(self, rubric: Rubric) -> str:
        if self.version:
            return self.version
        payload = f"{self.model}|{rubric.name}|{rubric.criteria}|{rubric.reference}|{PROMPT}"
        return hashlib.sha256(payload.encode()).hexdigest()[:12]

    @staticmethod
    def _parse(content: str) -> tuple[float, str]:
        try:
            data: dict[str, Any] = json.loads(unfence(content))
            value = float(data["score"])
        except Exception as exc:
            raise JudgeError(f"judge did not return a score: {content[:120]!r}") from exc
        if not 0.0 <= value <= 1.0:
            # Clamping 95 to 1.0 would report a perfect answer from a judge that
            # misunderstood the scale.
            raise JudgeError(f"judge returned {value}, which is outside 0..1")
        return value, str(data.get("reason") or "")


@dataclass
class ScoreStore:
    """Append-only JSONL of scores, joinable to a trace by `trace_id`."""

    path: str | Path = "scores.jsonl"
    _file: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._file = Path(self.path)

    def append(self, score: Score) -> None:
        self._file.parent.mkdir(parents=True, exist_ok=True)
        with self._file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(score)) + "\n")

    def scores(self) -> list[Score]:
        if not self._file.exists():
            return []
        return [
            Score(**json.loads(line))
            for line in self._file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def for_trace(self, trace_id: str) -> list[Score]:
        return [score for score in self.scores() if score.trace_id == trace_id]
