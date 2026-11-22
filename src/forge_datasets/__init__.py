"""Golden datasets for functional evaluation: inputs, expected outputs, rubrics, tags.

A dataset is a list of cases, so editing it from the API is list manipulation and
editing it in a spreadsheet is CSV import/export.

`version` moves only when the content does, and `save()` is idempotent: writing
identical content twice writes once and returns the same version. `content_hash`
is exposed so a report can pin the exact cases it was produced from, the way the
compliance packs are pinned by commit.

`dimension` is free text matching the board's Dimension field. The board validator
owns that vocabulary; restating it here would be a third copy to drift.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

FIELDS = ("id", "input", "expected", "context", "rubric", "dimension", "source")
REQUIRED = ("input", "expected")


class DatasetError(ValueError):
    """A dataset file or row cannot be read."""


@dataclass
class GoldenCase:
    input: str
    expected: str
    context: str = ""
    rubric: str = ""
    dimension: str = "Functional"
    source: str = ""
    id: str = ""


def _case(row: dict[str, Any], index: int) -> GoldenCase:
    unknown = sorted(set(row) - set(FIELDS))
    if unknown:
        raise DatasetError(
            f"case {index}: unknown field(s) {unknown}; valid fields are {', '.join(FIELDS)}"
        )
    missing = [name for name in REQUIRED if not str(row.get(name, "")).strip()]
    if missing:
        raise DatasetError(f"case {index}: missing {', '.join(missing)}")
    return GoldenCase(**{key: str(value) for key, value in row.items() if key in FIELDS})


@dataclass
class Dataset:
    name: str = "golden"
    cases: list[GoldenCase] = field(default_factory=list)
    version: int = 1

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            [asdict(case) for case in self.cases], sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @classmethod
    def load(cls, path: str | Path) -> Dataset:
        path = Path(path)
        if path.suffix.lower() == ".csv":
            return cls.from_csv(path)
        if path.suffix.lower() != ".json":
            raise DatasetError(f"{path.name}: expected .json or .csv")

        data = json.loads(path.read_text())
        if isinstance(data, list):
            return cls(name=path.stem, cases=[_case(row, index) for index, row in enumerate(data)])
        if not isinstance(data, dict):
            raise DatasetError(f"{path.name}: expected an object or an array of cases")
        return cls(
            name=str(data.get("name") or path.stem),
            version=int(data.get("version", 1)),
            cases=[_case(row, index) for index, row in enumerate(data.get("cases", []))],
        )

    @classmethod
    def from_csv(cls, path: str | Path) -> Dataset:
        path = Path(path)
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            reader.fieldnames = [name.strip() for name in reader.fieldnames or []]
            header = reader.fieldnames
            unknown = sorted(set(header) - set(FIELDS))
            if unknown:
                raise DatasetError(
                    f"{path.name}: unknown column(s) {unknown}; "
                    f"valid columns are {', '.join(FIELDS)}"
                )
            missing = [name for name in REQUIRED if name not in header]
            if missing:
                raise DatasetError(f"{path.name}: missing column(s) {', '.join(missing)}")
            cases = [_case(row, index) for index, row in enumerate(reader)]
        return cls(name=path.stem, cases=cases)

    def save(self, path: str | Path) -> int:
        """Write JSON and return the version. An unchanged dataset is not rewritten."""
        path = Path(path)
        if path.suffix.lower() == ".csv":
            raise DatasetError("save() writes JSON; use to_csv() for CSV")
        previous = self.load(path) if path.exists() else None
        if previous is not None and previous.cases == self.cases:
            self.version = previous.version
            return self.version

        self.version = (previous.version if previous else 0) + 1
        payload = {
            "name": self.name,
            "version": self.version,
            "content_hash": self.content_hash,
            "cases": [asdict(case) for case in self.cases],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        return self.version

    def to_csv(self, path: str | Path) -> None:
        columns: list[str] = list(FIELDS)
        with Path(path).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for case in self.cases:
                writer.writerow(asdict(case))
