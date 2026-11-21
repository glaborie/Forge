"""CLI over `forge_compliance.build_package`: JSON snapshot on stdin, markdown out."""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import UnknownFramework, build_package, split_selection, vocabulary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge_compliance",
        description="Build an evidence index for the frameworks an operator selected.",
    )
    parser.add_argument(
        "--frameworks",
        default=os.environ.get("FORGE_FRAMEWORKS", ""),
        help="comma- or semicolon-separated framework identifiers; empty means all",
    )
    parser.add_argument(
        "--matrix",
        default=os.environ.get("FORGE_MATRIX"),
        help="MATRIX.md, used to validate the selection against the §8 vocabulary",
    )
    args = parser.parse_args(argv)

    try:
        items = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"error: stdin is not the JSON array from fetch-items.sh: {exc}", file=sys.stderr)
        return 1
    if not isinstance(items, list):
        print("error: expected a JSON array (use .[], not .items[])", file=sys.stderr)
        return 1

    identifiers = vocabulary(args.matrix) if args.matrix else None
    try:
        package = build_package(
            items, frameworks=split_selection(args.frameworks), vocabulary=identifiers
        )
    except UnknownFramework as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(package, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
