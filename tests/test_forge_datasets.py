from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge_datasets import Dataset, DatasetError, GoldenCase

HEADER = "id,input,expected,context,rubric,dimension,source\n"


def dataset() -> Dataset:
    return Dataset(
        name="refunds",
        cases=[
            GoldenCase(
                id="g1",
                input="How long is the refund window?",
                expected="30 days",
                rubric="must state the 30-day window",
                dimension="Functional",
                source="support-ticket-1042",
            ),
            GoldenCase(id="g2", input="Do you ship to Norway?", expected="Yes"),
        ],
    )


def test_csv_import_keeps_every_column(tmp_path: Path) -> None:
    path = tmp_path / "golden.csv"
    path.write_text(
        HEADER
        + 'g1,"How long is the refund window?",30 days,"Refunds are accepted within 30 days.",'
        + '"must state 30 days",Functional,ticket-1\n'
        + "g2,Do you ship to Norway?,Yes,,,Functional,\n"
    )

    loaded = Dataset.load(path)

    assert [case.id for case in loaded.cases] == ["g1", "g2"]
    assert loaded.cases[0].rubric == "must state 30 days"
    assert loaded.cases[0].source == "ticket-1"
    assert loaded.cases[0].context == "Refunds are accepted within 30 days."
    assert loaded.cases[1].dimension == "Functional"
    assert loaded.name == "golden"


def test_an_unknown_column_is_rejected_rather_than_silently_dropped(tmp_path: Path) -> None:
    """A typo such as `expected_out` would import every case with no expectation."""
    path = tmp_path / "golden.csv"
    path.write_text("input,expected_out\nhi,hello\n")

    with pytest.raises(DatasetError) as caught:
        Dataset.load(path)

    assert "expected_out" in str(caught.value)
    assert "rubric" in str(caught.value)


def test_a_missing_required_column_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "golden.csv"
    path.write_text("input,rubric\nhi,be nice\n")

    with pytest.raises(DatasetError) as caught:
        Dataset.load(path)

    assert "missing column" in str(caught.value)
    assert "expected" in str(caught.value)


def test_a_case_with_no_input_names_its_position(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    path.write_text(json.dumps([{"input": "a", "expected": "b"}, {"expected": "no question"}]))

    with pytest.raises(DatasetError) as caught:
        Dataset.load(path)

    assert "case 1" in str(caught.value)
    assert "input" in str(caught.value)


def test_save_and_load_round_trip_including_the_version(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"

    version = dataset().save(path)
    loaded = Dataset.load(path)

    assert version == 1
    assert loaded.version == 1
    assert loaded.name == "refunds"
    assert loaded.cases == dataset().cases


def test_saving_unchanged_content_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    dataset().save(path)
    written = path.read_text()

    assert dataset().save(path) == 1
    assert path.read_text() == written


def test_an_edit_bumps_the_version(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    dataset().save(path)

    edited = Dataset.load(path)
    edited.cases[1].expected = "No, not yet"
    assert edited.save(path) == 2
    assert Dataset.load(path).cases[1].expected == "No, not yet"


def test_a_bare_json_array_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "golden.json"
    path.write_text(json.dumps([{"input": "2+2", "expected": "4"}]))

    loaded = Dataset.load(path)

    assert len(loaded.cases) == 1
    assert loaded.cases[0].dimension == "Functional"


def test_the_content_hash_pins_the_cases_not_the_version(tmp_path: Path) -> None:
    first = dataset()
    second = Dataset(cases=[GoldenCase(**case.__dict__) for case in first.cases])

    assert first.content_hash == second.content_hash

    second.cases[0].rubric = "different rubric"
    assert second.content_hash != first.content_hash


def test_csv_export_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "golden.csv"

    dataset().to_csv(path)
    loaded = Dataset.load(path)

    assert loaded.cases == dataset().cases
    assert path.read_text().startswith(HEADER)


def test_save_refuses_a_csv_path_rather_than_writing_json_into_it(tmp_path: Path) -> None:
    with pytest.raises(DatasetError) as caught:
        dataset().save(tmp_path / "golden.csv")

    assert "to_csv" in str(caught.value)


def test_an_unsupported_extension_is_named(tmp_path: Path) -> None:
    path = tmp_path / "golden.yaml"
    path.write_text("input: hi\n")

    with pytest.raises(DatasetError) as caught:
        Dataset.load(path)

    assert ".json or .csv" in str(caught.value)
