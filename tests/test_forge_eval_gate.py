from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from forge_datasets import Dataset, GoldenCase
from forge_eval import RUBRICS, Evaluator, evaluator_version, gate
from forge_eval.__main__ import answer, build_judges, main, prompt_for
from forge_harness import Reply


def score(metric: str, value: float) -> gate.Score:
    return gate.Score(
        metric=metric,
        value=value,
        reason="",
        trace_id="",
        version="v1",
        mode="reference-free",
        at="2026-01-01T00:00:00+00:00",
    )


def run_of(values: dict[str, list[float]]) -> gate.RecordedRun:
    cases = [
        gate.RecordedCase(
            id=f"c{index}",
            input="q",
            output="a",
            scores=[
                score(metric, value)
                for metric, series in values.items()
                for value in [series[index]]
            ],
        )
        for index in range(len(next(iter(values.values()))))
    ]
    return gate.RecordedRun(
        dataset="golden",
        dataset_hash="abc",
        judge="judge",
        at="2026-01-01",
        cases=cases,
        judge_model="judge",
        rubrics={metric: evaluator_version(RUBRICS[metric], "judge") for metric in values},
    )


def dataset_of(*cases: GoldenCase) -> Dataset:
    return Dataset(name="golden", cases=list(cases))


THRESHOLDS = {"hallucination": 0.7, "faithfulness": 0.7, "relevance": 0.8}


def test_means_above_the_thresholds_pass() -> None:
    report = gate.summarize(
        run_of({"hallucination": [0.9, 1.0], "faithfulness": [0.8, 0.8], "relevance": [0.9, 0.9]}),
        THRESHOLDS,
        dataset_hash="abc",
    )

    assert report.passed
    assert [metric.mean for metric in report.metrics] == [0.95, 0.8, 0.9]
    assert [metric.samples for metric in report.metrics] == [2, 2, 2]


def test_a_metric_below_its_threshold_fails_and_is_named() -> None:
    report = gate.summarize(
        run_of({"hallucination": [0.4, 0.4], "faithfulness": [0.9, 0.9], "relevance": [0.9, 0.9]}),
        THRESHOLDS,
        dataset_hash="abc",
    )

    assert not report.passed
    assert report.failed == ["hallucination"]


def test_a_threshold_for_an_unmeasured_metric_fails() -> None:
    """Silence is not a pass: a metric nobody scored cannot satisfy its threshold."""
    report = gate.summarize(
        run_of({"relevance": [1.0]}), {"relevance": 0.8, "context_recall": 0.7}, dataset_hash="abc"
    )

    assert not report.passed
    assert report.failed == ["context_recall"]
    assert report.metrics[1].samples == 0


def test_a_dataset_change_fails_the_gate() -> None:
    report = gate.summarize(
        run_of({"hallucination": [1.0]}), {"hallucination": 0.7}, dataset_hash="moved"
    )

    assert report.dataset_changed
    assert not report.passed
    assert report.failed == []  # the metrics are fine; the snapshot is stale
    assert "re-record" in report.render()


def test_the_report_round_trips_to_json(tmp_path: Path) -> None:
    report = gate.summarize(run_of({"hallucination": [0.5]}), THRESHOLDS, dataset_hash="abc")
    path = tmp_path / "nested" / "report.json"

    report.save(path)
    data = json.loads(path.read_text())

    assert data["passed"] is False
    assert data["dataset_changed"] is False
    assert data["metrics"][0]["metric"] == "hallucination"


def test_the_rendered_report_names_every_metric() -> None:
    report = gate.summarize(
        run_of({"hallucination": [0.9], "faithfulness": [0.9], "relevance": [0.9]}),
        THRESHOLDS,
        dataset_hash="abc",
    )
    rendered = report.render()

    for metric in THRESHOLDS:
        assert metric in rendered
    assert "PASS" in rendered


def test_no_thresholds_is_an_error() -> None:
    with pytest.raises(gate.GateError):
        gate.summarize(run_of({"hallucination": [1.0]}), {}, dataset_hash="abc")


def test_a_threshold_outside_zero_to_one_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps({"hallucination": 70}))

    with pytest.raises(gate.GateError) as caught:
        gate.load_thresholds(path)

    assert "outside 0..1" in str(caught.value)


def test_thresholds_must_be_an_object(tmp_path: Path) -> None:
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps([0.7]))

    with pytest.raises(gate.GateError):
        gate.load_thresholds(path)


def test_record_scores_every_case_once_per_judge() -> None:
    judges = {
        "relevance": Evaluator(
            ask=lambda _: json.dumps({"score": 0.9, "reason": "fine"}),
            rubric=RUBRICS["relevance"],
            model="judge",
        ),
        "faithfulness": Evaluator(
            ask=lambda _: json.dumps({"score": 0.6, "reason": "thin"}),
            rubric=RUBRICS["faithfulness"],
            model="judge",
        ),
    }
    dataset = dataset_of(
        GoldenCase(id="c1", input="q1", expected="e1", context="ctx"),
        GoldenCase(id="c2", input="q2", expected="e2", context="ctx"),
    )

    run = gate.record(dataset, lambda case: f"answer to {case.input}", judges)

    assert [case.id for case in run.cases] == ["c1", "c2"]
    assert [case.output for case in run.cases] == ["answer to q1", "answer to q2"]
    assert [[score.metric for score in case.scores] for case in run.cases] == [
        ["relevance", "faithfulness"],
        ["relevance", "faithfulness"],
    ]
    assert run.dataset_hash == dataset.content_hash


def test_a_recorded_run_round_trips(tmp_path: Path) -> None:
    run = run_of({"relevance": [0.5, 0.75]})
    path = tmp_path / "run.json"

    run.save(path)
    loaded = gate.RecordedRun.load(path)

    assert loaded == run


def test_a_rubric_edited_after_the_run_fails_the_gate() -> None:
    """A changed measuring instrument makes the recorded scores incomparable."""
    run = run_of({"relevance": [1.0]})
    run.judge_model = "judge"
    run.rubrics = {"relevance": "stale000000"}

    report = gate.summarize(run, {"relevance": 0.8}, dataset_hash="abc")

    assert report.stale_rubrics == ["relevance"]
    assert not report.passed
    assert "re-record" in report.render()


def test_an_unchanged_rubric_is_not_stale() -> None:
    run = run_of({"relevance": [1.0]})
    run.judge_model = "judge"
    run.rubrics = {"relevance": evaluator_version(RUBRICS["relevance"], "judge")}

    assert gate.summarize(run, {"relevance": 0.8}, dataset_hash="abc").passed


def test_a_run_without_rubric_versions_fails_rather_than_passing_silently() -> None:
    """An unpinned run cannot say which instrument produced its scores."""
    run = run_of({"relevance": [1.0]})
    run.rubrics = {}

    report = gate.summarize(run, {"relevance": 0.8}, dataset_hash="abc")

    assert report.unpinned
    assert not report.passed
    assert "no rubric versions" in report.render()


def test_check_passes_and_writes_an_artifact(tmp_path: Path) -> None:
    dataset = dataset_of(GoldenCase(id="c1", input="q", expected="e"))
    dataset_path = tmp_path / "golden.json"
    dataset.save(dataset_path)
    run = gate.RecordedRun(
        dataset="golden",
        dataset_hash=dataset.content_hash,
        judge="judge",
        at="2026-01-01",
        cases=[
            gate.RecordedCase(
                id="c1",
                input="q",
                output="a",
                scores=[score(metric, 0.95) for metric in THRESHOLDS],
            )
        ],
        judge_model="judge",
        rubrics={metric: evaluator_version(RUBRICS[metric], "judge") for metric in THRESHOLDS},
    )
    run_path = tmp_path / "run.json"
    run.save(run_path)
    report_path = tmp_path / "report.json"

    code = main(
        [
            "check",
            "--run",
            str(run_path),
            "--dataset",
            str(dataset_path),
            "--thresholds",
            str(_thresholds(tmp_path)),
            "--report",
            str(report_path),
        ]
    )

    assert code == 0
    assert json.loads(report_path.read_text())["passed"] is True


def test_check_fails_and_still_writes_the_artifact(tmp_path: Path) -> None:
    dataset_path = tmp_path / "golden.json"
    dataset_of(GoldenCase(id="c1", input="q", expected="e")).save(dataset_path)
    dataset_hash = Dataset.load(dataset_path).content_hash
    run = gate.RecordedRun(
        dataset="golden",
        dataset_hash=dataset_hash,
        judge="judge",
        at="2026-01-01",
        cases=[
            gate.RecordedCase(id="c1", input="q", output="a", scores=[score("hallucination", 0.1)])
        ],
    )
    run_path = tmp_path / "run.json"
    run.save(run_path)
    report_path = tmp_path / "report.json"

    code = main(
        [
            "check",
            "--run",
            str(run_path),
            "--dataset",
            str(dataset_path),
            "--thresholds",
            str(_thresholds(tmp_path)),
            "--report",
            str(report_path),
        ]
    )

    assert code == 1
    data = json.loads(report_path.read_text())
    assert data["passed"] is False
    assert "hallucination" in data["failed"]


def test_check_fails_when_the_dataset_moved_under_the_run(tmp_path: Path) -> None:
    dataset_path = tmp_path / "golden.json"
    dataset_of(GoldenCase(id="c1", input="q", expected="e")).save(dataset_path)
    run = gate.RecordedRun(dataset="golden", dataset_hash="stale", judge="judge", at="", cases=[])
    run_path = tmp_path / "run.json"
    run.save(run_path)

    code = main(
        [
            "check",
            "--run",
            str(run_path),
            "--dataset",
            str(dataset_path),
            "--thresholds",
            str(_thresholds(tmp_path)),
        ]
    )

    assert code == 1


def test_a_bad_threshold_file_exits_with_a_usage_error(tmp_path: Path) -> None:
    dataset_path = tmp_path / "golden.json"
    dataset_of(GoldenCase(id="c1", input="q", expected="e")).save(dataset_path)
    run = gate.RecordedRun(dataset="golden", dataset_hash="x", judge="j", at="", cases=[])
    run_path = tmp_path / "run.json"
    run.save(run_path)
    thresholds = tmp_path / "bad.json"
    thresholds.write_text(json.dumps({"hallucination": 2}))

    assert (
        main(
            [
                "check",
                "--run",
                str(run_path),
                "--dataset",
                str(dataset_path),
                "--thresholds",
                str(thresholds),
            ]
        )
        == 2
    )


class FakeTarget:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self.text = text

    def send(self, prompt: str) -> Any:
        return Reply(status=self.status, text=self.text, latency_ms=1.0)


def test_a_dead_target_aborts_the_recording_instead_of_scoring_zero() -> None:
    """A transport failure is not a worse answer; scoring it would blame the model."""
    case = GoldenCase(id="c", input="q", expected="e")

    with pytest.raises(gate.GateError) as caught:
        answer(FakeTarget(0, "transport error: connection refused"), case)  # type: ignore[arg-type]

    assert "no response" in str(caught.value)
    assert "connection refused" in str(caught.value)


def test_an_http_error_aborts_the_recording() -> None:
    case = GoldenCase(id="c", input="q", expected="e")

    with pytest.raises(gate.GateError) as caught:
        answer(FakeTarget(401, "unauthorized"), case)  # type: ignore[arg-type]

    assert "401" in str(caught.value)


def test_a_200_answer_is_returned_and_may_be_blocked_text() -> None:
    case = GoldenCase(id="c", input="q", expected="e")

    assert answer(FakeTarget(200, ""), case) == ""  # type: ignore[arg-type]


def test_an_unknown_threshold_metric_is_rejected() -> None:
    with pytest.raises(gate.GateError) as caught:
        build_judges("judge", {"vibes": 0.9})

    assert "no rubric for vibes" in str(caught.value)


def test_the_prompt_carries_the_context_to_the_target() -> None:
    case = GoldenCase(id="c", input="How long?", expected="30 days", context="30 days.")

    prompt = prompt_for(case)

    assert prompt.startswith("Context:\n30 days.")
    assert "Question: How long?" in prompt


def test_a_case_without_context_is_sent_as_the_bare_question() -> None:
    assert prompt_for(GoldenCase(id="c", input="Hi", expected="-")) == "Hi"


def _thresholds(tmp_path: Path) -> Path:
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(THRESHOLDS))
    return path
