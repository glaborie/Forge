from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from forge_eval import (
    RUBRICS,
    Evaluator,
    JudgeError,
    Rubric,
    Sample,
    Score,
    ScoreStore,
    build_prompt,
    current_trace_id,
    unfence,
)


def judge_returning(content: str, *, rubric: Rubric | None = None) -> tuple[Evaluator, list[str]]:
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return content

    rubric = rubric or RUBRICS["relevance"]
    return Evaluator(ask=ask, rubric=rubric, model="test/judge"), prompts


def verdict(score: float, reason: str = "looks right") -> str:
    return json.dumps({"score": score, "reason": reason})


def test_a_reference_free_rubric_scores_without_an_expected_answer() -> None:
    evaluator, _ = judge_returning(verdict(0.8))

    score = evaluator.evaluate(Sample(input="q", output="a"))

    assert score.metric == "relevance"
    assert score.value == 0.8
    assert score.reason == "looks right"
    assert score.mode == "reference-free"


def test_a_reference_based_rubric_refuses_a_sample_without_reference() -> None:
    evaluator, prompts = judge_returning(verdict(1.0), rubric=RUBRICS["hallucination"])

    with pytest.raises(JudgeError) as caught:
        evaluator.evaluate(Sample(input="q", output="a"))

    assert "expected answer" in str(caught.value)
    assert prompts == []  # nothing was sent to the model


def test_the_reference_appears_in_the_prompt_only_in_reference_mode() -> None:
    reference_mode, with_reference = judge_returning(verdict(1.0), rubric=RUBRICS["hallucination"])
    free_mode, without = judge_returning(verdict(1.0))

    reference_mode.evaluate(Sample(input="q", output="a", expected="the reference"))
    free_mode.evaluate(Sample(input="q", output="a", expected="the reference"))

    assert "Reference answer:" in with_reference[0]
    assert "the reference" in with_reference[0]
    assert "Reference answer:" not in without[0]


def test_context_is_included_when_the_sample_carries_it() -> None:
    evaluator, prompts = judge_returning(verdict(0.9), rubric=RUBRICS["faithfulness"])

    evaluator.evaluate(Sample(input="q", output="a", context="the refund window is 30 days"))

    assert "Context:" in prompts[0]
    assert "the refund window is 30 days" in prompts[0]


def test_a_fenced_json_answer_is_accepted() -> None:
    evaluator, _ = judge_returning('```json\n{"score": 0.25, "reason": "thin"}\n```')

    assert evaluator.evaluate(Sample(input="q", output="a")).value == 0.25


def test_an_out_of_range_score_is_rejected_rather_than_clamped() -> None:
    """A judge that answers 95 has misunderstood the scale; 1.0 would hide that."""
    evaluator, _ = judge_returning(verdict(95))

    with pytest.raises(JudgeError) as caught:
        evaluator.evaluate(Sample(input="q", output="a"))

    assert "outside 0..1" in str(caught.value)


def test_an_unparseable_answer_names_what_the_judge_said() -> None:
    evaluator, _ = judge_returning("I think it is quite good.")

    with pytest.raises(JudgeError) as caught:
        evaluator.evaluate(Sample(input="q", output="a"))

    assert "did not return a score" in str(caught.value)
    assert "quite good" in str(caught.value)


def test_the_version_changes_when_the_rubric_changes() -> None:
    original = Rubric("relevance", "answers the question")
    edited = Rubric("relevance", "answers the question, briefly")
    one, _ = judge_returning(verdict(1.0), rubric=original)
    two, _ = judge_returning(verdict(1.0), rubric=edited)

    assert (
        one.evaluate(Sample(input="q", output="a")).version
        != two.evaluate(Sample(input="q", output="a")).version
    )


def test_the_version_is_stable_for_the_same_evaluator() -> None:
    rubric = Rubric("relevance", "answers the question")
    one, _ = judge_returning(verdict(1.0), rubric=rubric)
    two, _ = judge_returning(verdict(1.0), rubric=rubric)

    assert (
        one.evaluate(Sample(input="q", output="a")).version
        == two.evaluate(Sample(input="q", output="a")).version
    )


def test_an_explicit_version_overrides_the_derived_one() -> None:
    evaluator, _ = judge_returning(verdict(1.0))
    evaluator.version = "v3"

    assert evaluator.evaluate(Sample(input="q", output="a")).version == "v3"


def test_a_per_call_rubric_override_wins_and_is_recorded_in_the_version() -> None:
    evaluator, prompts = judge_returning(verdict(0.5))
    custom = Rubric("refunds", "states the 30-day window")

    score = evaluator.evaluate(Sample(input="q", output="a"), rubric=custom)

    assert score.metric == "refunds"
    assert "states the 30-day window" in prompts[0]
    assert score.version != evaluator.evaluate(Sample(input="q", output="a")).version


def test_scores_are_stored_per_trace(tmp_path: Path) -> None:
    store = ScoreStore(tmp_path / "nested" / "scores.jsonl")
    evaluator, _ = judge_returning(verdict(0.7))

    evaluator.evaluate(Sample(input="q", output="a"), trace_id="aaa", store=store)
    evaluator.evaluate(Sample(input="q", output="a"), trace_id="bbb", store=store)

    assert [score.trace_id for score in store.scores()] == ["aaa", "bbb"]
    assert len(store.for_trace("aaa")) == 1
    assert store.for_trace("nope") == []


def test_a_score_without_a_store_is_still_returned() -> None:
    evaluator, _ = judge_returning(verdict(1.0))

    assert evaluator.evaluate(Sample(input="q", output="a")).value == 1.0


def test_the_active_trace_id_is_used_when_none_is_passed(tmp_path: Path) -> None:
    trace.set_tracer_provider(TracerProvider())
    tracer = trace.get_tracer("test")
    store = ScoreStore(tmp_path / "scores.jsonl")
    evaluator, _ = judge_returning(verdict(1.0))

    with tracer.start_as_current_span("case") as span:
        evaluator.evaluate(Sample(input="q", output="a"), store=store)

    assert store.scores()[0].trace_id == f"{span.get_span_context().trace_id:032x}"
    assert current_trace_id() == ""


def test_the_four_metrics_from_the_story_exist_with_the_right_modes() -> None:
    expected = {
        "hallucination": True,
        "faithfulness": False,
        "relevance": False,
        "context_recall": True,
    }

    assert {name: rubric.reference for name, rubric in RUBRICS.items()} == expected


def test_a_rubric_without_criteria_is_rejected() -> None:
    with pytest.raises(JudgeError):
        Rubric("empty", "   ")


def test_the_prompt_states_the_scoring_direction() -> None:
    prompt = build_prompt(RUBRICS["relevance"], Sample(input="q", output="a"))

    assert "Score 1.0 when the answer fully satisfies" in prompt


def test_the_store_round_trips_every_field(tmp_path: Path) -> None:
    store = ScoreStore(tmp_path / "scores.jsonl")
    score = Score(
        "relevance", 0.5, "meh", "t1", "abc123", "reference-free", "2026-01-01T00:00:00+00:00"
    )

    store.append(score)

    assert store.scores() == [score]


def test_a_store_accepts_a_string_path(tmp_path: Path) -> None:
    """The documented usage is `ScoreStore("scores.jsonl")`, not a Path."""
    store = ScoreStore(str(tmp_path / "scores.jsonl"))
    evaluator, _ = judge_returning(verdict(1.0))

    evaluator.evaluate(Sample(input="q", output="a"), trace_id="t1", store=store)

    assert [score.trace_id for score in store.for_trace("t1")] == ["t1"]


def test_an_empty_store_reads_as_no_scores(tmp_path: Path) -> None:
    assert ScoreStore(tmp_path / "missing.jsonl").scores() == []


def test_blank_lines_in_the_store_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "scores.jsonl"
    path.write_text("\n" + json.dumps(_as_dict("t1")) + "\n\n")

    assert len(ScoreStore(path).scores()) == 1


def _as_dict(trace_id: str) -> dict[str, Any]:
    return {
        "metric": "relevance",
        "value": 1.0,
        "reason": "",
        "trace_id": trace_id,
        "version": "v1",
        "mode": "reference-free",
        "at": "2026-01-01T00:00:00+00:00",
    }


def test_unfence_leaves_plain_json_alone() -> None:
    assert unfence('{"score": 1}') == '{"score": 1}'
