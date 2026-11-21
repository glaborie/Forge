"""Turn a project snapshot into an evidence index for selected frameworks.

The operator chooses the frameworks; this module records that choice. It never
infers applicability from a target's sector or jurisdiction — FINMA applies
because someone said the target is supervised, not because it behaves like a bank.

Importable on purpose: the CLI is a thin wrapper, so a dashboard can call the
same function without shelling out or reimplementing the report.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

_SECTION = "## 8. Appendix"
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|")


class UnknownFramework(ValueError):
    """A selected name is not in the MATRIX §8 vocabulary."""

    def __init__(self, unknown: Sequence[str], vocabulary: Sequence[str]) -> None:
        self.unknown = tuple(unknown)
        self.vocabulary = tuple(vocabulary)
        super().__init__(
            f"not a Standard identifier: {', '.join(self.unknown)}\n"
            f"valid: {'; '.join(self.vocabulary)}"
        )


def vocabulary(matrix_path: str | Path) -> tuple[str, ...]:
    """Read the identifiers from the §8 table, the one home for the list."""
    identifiers: list[str] = []
    inside = False
    for line in Path(matrix_path).read_text(encoding="utf-8").splitlines():
        if line.startswith(_SECTION):
            inside = True
            continue
        if inside and line.startswith("### "):
            break
        if inside:
            match = _ROW.match(line)
            if match:
                identifiers.append(match.group(1))
    return tuple(identifiers)


def split_selection(selection: str) -> list[str]:
    """Accept `A,B` or `A; B` because both spellings reach us from a shell."""
    return [part.strip() for part in re.split(r"[,;]", selection) if part.strip()]


def build_package(
    items: Iterable[dict[str, Any]],
    *,
    frameworks: Iterable[str] = (),
    vocabulary: Sequence[str] | None = None,
) -> str:
    """Markdown rows of `(framework, control)`, one per claim on the board."""
    wanted = [name for name in (f.strip() for f in frameworks) if name]
    if vocabulary is not None:
        unknown = [name for name in wanted if name not in vocabulary]
        if unknown:
            raise UnknownFramework(unknown, vocabulary)

    rows: list[tuple[str, int, dict[str, Any]]] = []
    for item in items:
        if item.get("type") != "Issue":
            continue
        claims = [part.strip() for part in (item.get("standard") or "").split(";") if part.strip()]
        for name in claims:
            if wanted and name not in wanted:
                continue
            rows.append((name, int(item.get("number") or 0), item))
    rows.sort(key=lambda row: (row[0], row[1]))

    title = (
        f"Evidence package: {', '.join(wanted)}" if wanted else "Evidence package: all standards"
    )
    out = [
        f"# {title}",
        "",
        (
            "Frameworks selected by the operator. The package records that selection; it does not"
            " decide applicability, and it does not assert that any control's evidence is complete."
        ),
        "",
    ]
    if not rows:
        out += [
            "No control references the selected frameworks."
            if wanted
            else "No control has a Standard value.",
            "",
        ]
        return "\n".join(out)

    out += [
        "The artifact that proves each control is named in the story.",
        "",
        "| Standard | # | Control | Status | Milestone | Dimension | Epic |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for name, number, item in rows:
        url = item.get("url") or ""
        cells = [
            name,
            f"[{number}]({url})" if url else str(number),
            (item.get("title") or "").strip(),
            item.get("status") or "",
            item.get("milestone") or "",
            item.get("dimension") or "",
            item.get("epic") or "",
        ]
        out.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    out += ["", f"{len(rows)} control(s).", ""]
    return "\n".join(out)
