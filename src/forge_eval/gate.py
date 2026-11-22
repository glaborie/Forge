"""Functional evaluation gate: per-metric rates over a recorded run, against thresholds.

CI cannot reach a live model, so the gate is offline. `make eval` records answers
and judge scores into a run file, the run file is committed, and CI re-derives the
rates from it. A gate that re-judged live would either spend money on every pull
request or silently skip on forks, and a gate that skips is not a gate.

The recorded run carries the dataset's content hash. Editing the dataset without
re-recording fails the gate, because a snapshot that keeps passing after the
questions changed is worse than no snapshot at all.

The context of a case is sent to the target by `make eval`, not only to the judge:
a model that never saw the source material is being asked for world knowledge, and
a faithfulness score over that measures the wrong thing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import RUBRICS, Evaluator, Sample, Score, evaluator_version

# Chosen before the first recording, then left alone. Lowering a threshold to make
# a run pass is how an evaluation gate stops meaning anything.
DEFAULT_THRESHOLDS: dict[str, float] = {
    "hallucination": 0.7,
    "faithfulness": 0.7,
    "relevance": 0.8,
}


class GateError(RuntimeError):
    """The gate cannot be evaluated (bad thresholds, missing metric)."""


@dataclass(frozen=True)
class MetricSummary:
    metric: str
    mean: float
    samples: int
    minimum: float
    version: str

    @property
    def passed(self) -> bool:
        return self.samples > 0 and self.mean >= self.minimum


@dataclass
class Report:
    dataset: str
    dataset_hash: str
    recorded_hash: str
    judge: str
    cases: int
    metrics: list[MetricSummary] = field(default_factory=list)
    stale_rubrics: list[str] = field(default_factory=list)
    unpinned: bool = False

    @property
    def dataset_changed(self) -> bool:
        return self.dataset_hash != self.recorded_hash

    @property
    def failed(self) -> list[str]:
        return [metric.metric for metric in self.metrics if not metric.passed]

    @property
    def passed(self) -> bool:
        return (
            not self.dataset_changed
            and not self.stale_rubrics
            and not self.unpinned
            and not self.failed
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["passed"] = self.passed
        data["failed"] = self.failed
        data["dataset_changed"] = self.dataset_changed
        return data

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    def render(self) -> str:
        lines = [
            (
                f"dataset  {self.dataset}  hash {self.dataset_hash[:12]}  "
                f"{self.cases} case{'' if self.cases == 1 else 's'}  judge {self.judge}"
            ),
            f"{'metric':<16}{'mean':>6}{'min':>7}{'n':>5}  result",
        ]
        for metric in self.metrics:
            result = "pass" if metric.passed else "FAIL"
            lines.append(
                f"{metric.metric:<16}{metric.mean:>6.2f}{metric.minimum:>7.2f}"
                f"{metric.samples:>5}  {result}"
            )
        if self.dataset_changed:
            lines.append("dataset changed since the run was recorded; re-record with `make eval`")
        if self.stale_rubrics:
            lines.append(
                f"rubric changed since the run was recorded ({', '.join(self.stale_rubrics)})"
                "; re-record with `make eval`"
            )
        if self.unpinned:
            lines.append("run carries no rubric versions, so its scores cannot be trusted")
        lines.append("PASS" if self.passed else "FAIL")
        return "\n".join(lines)


@dataclass
class RecordedCase:
    id: str
    input: str
    output: str
    scores: list[Score]


@dataclass
class RecordedRun:
    dataset: str
    dataset_hash: str
    judge: str
    at: str
    cases: list[RecordedCase]
    judge_model: str = ""
    rubrics: dict[str, str] = field(default_factory=dict)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> RecordedRun:
        data = json.loads(Path(path).read_text())
        return cls(
            dataset=str(data["dataset"]),
            dataset_hash=str(data["dataset_hash"]),
            judge=str(data.get("judge", "")),
            at=str(data.get("at", "")),
            judge_model=str(data.get("judge_model", "")),
            rubrics={str(k): str(v) for k, v in data.get("rubrics", {}).items()},
            cases=[
                RecordedCase(
                    id=str(case.get("id", "")),
                    input=str(case.get("input", "")),
                    output=str(case.get("output", "")),
                    scores=[Score(**score) for score in case.get("scores", [])],
                )
                for case in data.get("cases", [])
            ],
        )


def record(
    dataset: Any,
    answers: Callable[[Any], str],
    judges: dict[str, Evaluator],
) -> RecordedRun:
    """Ask the target for an answer per case, then score it once per judge."""
    recorded: list[RecordedCase] = []
    for case in dataset.cases:
        output = answers(case)
        sample = Sample(
            input=case.input, output=output, expected=case.expected, context=case.context
        )
        recorded.append(
            RecordedCase(
                id=case.id,
                input=case.input,
                output=output,
                scores=[judge.evaluate(sample) for judge in judges.values()],
            )
        )
    models = {judge.model for judge in judges.values()}
    return RecordedRun(
        dataset=dataset.name,
        dataset_hash=dataset.content_hash,
        judge=", ".join(sorted(model or "judge" for model in models)),
        at=datetime.now(UTC).isoformat(timespec="seconds"),
        cases=recorded,
        # One model, or none: a version is only comparable when the instrument is known.
        judge_model=models.pop() if len(models) == 1 else "",
        rubrics={score.metric: score.version for case in recorded for score in case.scores},
    )


def summarize(run: RecordedRun, thresholds: dict[str, float], *, dataset_hash: str) -> Report:
    if not thresholds:
        raise GateError("no thresholds configured")

    values: dict[str, list[float]] = {}
    versions: dict[str, str] = {}
    for case in run.cases:
        for score in case.scores:
            values.setdefault(score.metric, []).append(score.value)
            versions.setdefault(score.metric, score.version)

    metrics = []
    for metric, minimum in thresholds.items():
        observed = values.get(metric)
        if not observed:
            # A threshold for a metric nobody scored must fail: silence is not a pass.
            metrics.append(MetricSummary(metric, 0.0, 0, minimum, ""))
            continue
        metrics.append(
            MetricSummary(
                metric=metric,
                mean=sum(observed) / len(observed),
                samples=len(observed),
                minimum=minimum,
                version=versions.get(metric, ""),
            )
        )
    return Report(
        dataset=run.dataset,
        dataset_hash=dataset_hash,
        recorded_hash=run.dataset_hash,
        judge=run.judge,
        cases=len(run.cases),
        metrics=metrics,
        stale_rubrics=stale_rubrics(run),
        # A run recorded before pinning existed must fail, not pass by omission.
        unpinned=not run.judge_model or not run.rubrics,
    )


def stale_rubrics(run: RecordedRun) -> list[str]:
    """Rubrics edited after the run was recorded, so its scores are not comparable."""
    if not run.judge_model:
        return []
    return sorted(
        metric
        for metric, version in run.rubrics.items()
        if metric in RUBRICS and evaluator_version(RUBRICS[metric], run.judge_model) != version
    )


def load_thresholds(path: str | Path) -> dict[str, float]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise GateError("thresholds must be an object of metric: minimum")
    thresholds = {}
    for metric, minimum in data.items():
        value = float(minimum)
        if not 0.0 <= value <= 1.0:
            raise GateError(f"threshold for {metric} is {value}, which is outside 0..1")
        thresholds[str(metric)] = value
    return thresholds
