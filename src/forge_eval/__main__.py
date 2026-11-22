"""The functional evaluation gate.

    make eval                                    # record a run against the live target
    python -m forge_eval check --run evaluation/run.json \
        --dataset evaluation/golden.json --report evaluation-report.json

`run` needs a target and a judge model, so it is an operator command. `check` is
offline and deterministic, which is why CI runs it on every pull request.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from forge_datasets import Dataset
from forge_harness import Target
from forge_harness.auth import grants_from_env

from . import RUBRICS, Evaluator, gate
from .openrouter import ask as ask_model

DEFAULT_RUN = "evaluation/run.json"
DEFAULT_DATASET = "evaluation/golden.json"
DEFAULT_THRESHOLDS = "evaluation/thresholds.json"


def prompt_for(case: Any) -> str:
    """Send the source material with the question, so the target can be faithful to it."""
    if not case.context.strip():
        return case.input
    return f"Context:\n{case.context.strip()}\n\nQuestion: {case.input.strip()}"


def build_judges(model: str, thresholds: dict[str, float]) -> dict[str, Evaluator]:
    unknown = sorted(set(thresholds) - set(RUBRICS))
    if unknown:
        raise gate.GateError(
            f"no rubric for {', '.join(unknown)}; have: {', '.join(sorted(RUBRICS))}"
        )
    return {
        metric: Evaluator(ask=ask_model(model=model), rubric=RUBRICS[metric], model=model)
        for metric in thresholds
    }


def build_target(args: argparse.Namespace) -> Target:
    token = args.token
    if token is None:
        grants = grants_from_env()
        if args.role not in grants:
            raise gate.GateError(
                f"no credential for role {args.role!r}; "
                f"have: {', '.join(grants) or 'none'}. Set it in .env or pass --token."
            )
        token = grants[args.role]
    return Target(
        args.target,
        path=args.path,
        token=token,
        send_model=args.path.rstrip("/").endswith("completions"),
    )


def summarize(args: argparse.Namespace) -> int:
    dataset = Dataset.load(args.dataset)
    run = gate.RecordedRun.load(args.run)
    thresholds = gate.load_thresholds(args.thresholds)
    report = gate.summarize(run, thresholds, dataset_hash=dataset.content_hash)

    print(report.render())
    if args.report:
        report.save(args.report)
        print(f"report   {args.report}")
    return 0 if report.passed else 1


def record(args: argparse.Namespace) -> int:
    dataset = Dataset.load(args.dataset)
    thresholds = gate.load_thresholds(args.thresholds)
    judges = build_judges(args.judge_model, thresholds)
    target = build_target(args)

    run = gate.record(dataset, lambda case: target.send(prompt_for(case)).text, judges)
    run.save(args.out)

    report = gate.summarize(run, thresholds, dataset_hash=dataset.content_hash)
    print(report.render())
    print(f"recorded {args.out}")
    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forge_eval", description="Functional evaluation gate.")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="record a live run with judge scores")
    run.add_argument("--dataset", default=DEFAULT_DATASET)
    run.add_argument("--target", required=True, help="base URL, e.g. http://localhost:8000")
    run.add_argument("--path", default="/v1/chat/completions")
    run.add_argument("--role", default="admin", help="credential role from .env")
    run.add_argument("--token", default=None, help="bearer token instead of a .env grant")
    run.add_argument("--judge-model", default=None, help="defaults to OPENROUTER_MODEL")
    run.add_argument("--thresholds", default=DEFAULT_THRESHOLDS)
    run.add_argument("--out", default=DEFAULT_RUN)
    run.set_defaults(handler=record)

    check = commands.add_parser("check", help="score a recorded run against thresholds")
    check.add_argument("--run", default=DEFAULT_RUN)
    check.add_argument("--dataset", default=DEFAULT_DATASET)
    check.add_argument("--thresholds", default=DEFAULT_THRESHOLDS)
    check.add_argument("--report", default=None, help="write the pass/fail artifact here")
    check.set_defaults(handler=summarize)

    args = parser.parse_args(argv)
    if args.command == "run" and not args.judge_model:
        import os

        args.judge_model = os.getenv("OPENROUTER_MODEL")
    if args.command == "run" and not args.judge_model:
        parser.exit(2, "error: no judge model: pass --judge-model or set OPENROUTER_MODEL\n")

    try:
        return int(args.handler(args))
    except (gate.GateError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
