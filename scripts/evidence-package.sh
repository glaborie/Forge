#!/usr/bin/env bash
# Build an evidence index for the frameworks an operator selected.
#
#   ./scripts/fetch-items.sh 5 | ./scripts/evidence-package.sh "Swiss FADP,FINMA"
#   FORGE_FRAMEWORKS="Swiss FADP" ./scripts/fetch-items.sh 5 | ./scripts/evidence-package.sh
#
# Applicability is the operator's decision: this script never infers a framework
# from the target, and it refuses a name that is not in the MATRIX §8 vocabulary.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SELECTION="${1:-${FORGE_FRAMEWORKS:-}}"

# A heredoc occupies stdin, so the snapshot arrives through a file instead.
SNAPSHOT="$(mktemp)"
trap 'rm -f "$SNAPSHOT"' EXIT
cat > "$SNAPSHOT"

python3 - "$SELECTION" "$SNAPSHOT" "$ROOT/MATRIX.md" <<'PY'
import json
import re
import sys

selection, snapshot, matrix = sys.argv[1], sys.argv[2], sys.argv[3]

# The vocabulary has one home: the §8 table. Parsing it beats a third copy that
# drifts from validate-project.sh.
vocabulary: list[str] = []
in_section = False
for line in open(matrix, encoding="utf-8"):
    if line.startswith("## 8. Appendix"):
        in_section = True
        continue
    if in_section and line.startswith("### "):
        break
    if in_section:
        match = re.match(r"^\|\s*`([^`]+)`\s*\|", line)
        if match:
            vocabulary.append(match.group(1))

wanted = [part.strip() for part in re.split(r"[,;]", selection) if part.strip()]
unknown = [name for name in wanted if name not in vocabulary]
if unknown:
    print(f"error: not a Standard identifier: {', '.join(unknown)}", file=sys.stderr)
    print("valid: " + "; ".join(vocabulary), file=sys.stderr)
    sys.exit(1)

try:
    with open(snapshot, encoding="utf-8") as handle:
        items = json.load(handle)
except (json.JSONDecodeError, OSError) as exc:
    print(f"error: stdin is not the JSON array from fetch-items.sh: {exc}", file=sys.stderr)
    sys.exit(1)
if not isinstance(items, list):
    print("error: expected a JSON array (use .[], not .items[])", file=sys.stderr)
    sys.exit(1)


def standards(item):
    return [part.strip() for part in (item.get("standard") or "").split(";") if part.strip()]


rows = []
for item in items:
    if item.get("type") != "Issue":
        continue
    for name in standards(item):
        if wanted and name not in wanted:
            continue
        rows.append((name, int(item.get("number") or 0), item))

rows.sort(key=lambda row: (row[0], row[1]))

title = f"Evidence package: {', '.join(wanted)}" if wanted else "Evidence package: all standards"
out = [f"# {title}", ""]
out.append(
    "Frameworks selected by the operator. The package records that selection; it does not"
    " decide applicability, and it does not assert that any control's evidence is complete."
)
out.append("")
if not rows:
    out += ["No control references the selected frameworks." if wanted else "No control has a Standard value.", ""]
else:
    out += [
        "The artifact that proves each control is named in the story.",
        "",
        "| Standard | # | Control | Status | Milestone | Dimension | Epic |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for name, number, item in rows:
        url = item.get("url") or ""
        link = f"[{number}]({url})" if url else str(number)
        cells = [
            name,
            link,
            (item.get("title") or "").strip(),
            item.get("status") or "",
            item.get("milestone") or "",
            item.get("dimension") or "",
            item.get("epic") or "",
        ]
        out.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    out += ["", f"{len(rows)} control(s).", ""]

print("\n".join(out), end="")
PY
