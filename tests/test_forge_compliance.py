"""The importable API a dashboard will call, independent of the shell wrapper."""

from __future__ import annotations

import pytest

from forge_compliance import UnknownFramework, build_package, split_selection, vocabulary

ITEMS = [
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
        "type": "Issue",
        "number": 19,
        "title": "D2. Deploy output guardrails",
        "status": "Done",
        "milestone": "M2 Guardrails",
        "dimension": "Security",
        "epic": "Epic D",
        "standard": "Swiss FADP",
        "url": "",
    },
]


def test_the_vocabulary_comes_from_the_matrix() -> None:
    identifiers = vocabulary("MATRIX.md")

    assert "Swiss FADP" in identifiers
    assert "FINMA" in identifiers
    assert len(identifiers) >= 13
    assert "Standard" not in identifiers


def test_split_accepts_both_separators() -> None:
    assert split_selection("Swiss FADP, FINMA;EU AI Act") == [
        "Swiss FADP",
        "FINMA",
        "EU AI Act",
    ]


def test_rows_are_sorted_by_framework_then_number() -> None:
    package = build_package(ITEMS)

    positions = [package.index("EU AI Act"), package.index("Swiss FADP | 19")]
    assert positions == sorted(positions)


def test_an_unknown_framework_raises_with_the_valid_list() -> None:
    with pytest.raises(UnknownFramework) as caught:
        build_package(ITEMS, frameworks=["GDPR"], vocabulary=("Swiss FADP",))

    assert caught.value.unknown == ("GDPR",)
    assert "valid: Swiss FADP" in str(caught.value)


def test_without_a_vocabulary_the_selection_is_not_checked() -> None:
    """A caller that has already validated must not be forced to pass the list."""

    assert "Swiss FADP" in build_package(ITEMS, frameworks=["Swiss FADP"])


def test_the_selection_is_recorded_in_the_header() -> None:
    assert build_package(ITEMS, frameworks=["FINMA"]).startswith("# Evidence package: FINMA")
    assert build_package(ITEMS).startswith("# Evidence package: all standards")
