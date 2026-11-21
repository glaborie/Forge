from __future__ import annotations

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "evidence-package.sh"

ITEMS = [
    {
        "type": "Issue",
        "number": 19,
        "title": "D2. Deploy output guardrails",
        "status": "Done",
        "milestone": "M2 Guardrails",
        "dimension": "Security",
        "epic": "Epic D",
        "standard": "OWASP LLM Top 10; Swiss FADP",
        "url": "https://example.test/19",
    },
    {
        "type": "Issue",
        "number": 57,
        "title": "H4. Reconcile the audit ledger",
        "status": "Backlog",
        "milestone": "M1 Baseline",
        "dimension": "Cross-cutting",
        "epic": "Epic H",
        "standard": "EU AI Act; Swiss FADP",
        "url": "",
    },
    {
        "type": "PullRequest",
        "number": 77,
        "title": "chore: a pull request",
        "status": "",
        "milestone": "",
        "dimension": "",
        "epic": "",
        "standard": "Swiss FADP",
        "url": "",
    },
]


def run(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args],
        input=stdin if stdin is not None else json.dumps(ITEMS),
        capture_output=True,
        text=True,
        check=False,
    )


def test_filter_keeps_only_the_requested_standard() -> None:
    result = run("Swiss FADP")

    assert result.returncode == 0
    assert "Evidence package: Swiss FADP" in result.stdout
    assert "D2. Deploy output guardrails" in result.stdout
    assert "H4. Reconcile the audit ledger" in result.stdout
    assert "2 control(s)." in result.stdout


def test_filter_excludes_other_standards() -> None:
    result = run("EU AI Act")

    assert "H4. Reconcile the audit ledger" in result.stdout
    assert "D2. Deploy output guardrails" not in result.stdout


def test_pull_requests_are_not_controls() -> None:
    result = run("Swiss FADP")

    assert "chore: a pull request" not in result.stdout


def test_a_standard_with_no_controls_says_so() -> None:
    result = run("FINMA Guidance 08/2024")

    assert result.returncode == 0
    assert "No control references FINMA Guidance 08/2024." in result.stdout


def test_without_a_filter_every_standard_appears() -> None:
    result = run()

    assert "Evidence package: all standards" in result.stdout
    assert "OWASP LLM Top 10" in result.stdout
    assert "EU AI Act" in result.stdout
    # One row per (standard, control) pair: two standards on each of two items.
    assert "4 control(s)." in result.stdout


def test_a_bare_object_is_rejected_with_a_pointer() -> None:
    result = run(stdin=json.dumps({"items": ITEMS}))

    assert result.returncode == 1
    assert "use .[], not .items[]" in result.stderr


def test_invalid_json_is_rejected() -> None:
    result = run(stdin="not json")

    assert result.returncode == 1
    assert "not the JSON array" in result.stderr
