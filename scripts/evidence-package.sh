#!/usr/bin/env bash
# Build a per-standard evidence index from a project snapshot on stdin.
#
#   ./scripts/fetch-items.sh 5 | ./scripts/evidence-package.sh "Swiss FADP"
#   ./scripts/fetch-items.sh 5 | ./scripts/evidence-package.sh
#
# This indexes the controls, it does not assert that their evidence is complete:
# the artifact that proves each control is named in the story itself.
set -euo pipefail

STANDARD="${1:-}"

# A heredoc occupies stdin, so the snapshot arrives through a file instead.
SNAPSHOT="$(mktemp)"
trap 'rm -f "$SNAPSHOT"' EXIT
cat > "$SNAPSHOT"

python3 - "$STANDARD" "$SNAPSHOT" <<'PY'
import json
import sys

wanted = sys.argv[1].strip()

try:
    with open(sys.argv[2], encoding="utf-8") as handle:
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
        if wanted and name != wanted:
            continue
        rows.append((name, int(item.get("number") or 0), item))

rows.sort(key=lambda row: (row[0], row[1]))

title = f"Evidence package: {wanted}" if wanted else "Evidence package: all standards"
out = [f"# {title}", ""]
if not rows:
    out += [f"No control references {wanted}." if wanted else "No control has a Standard value.", ""]
else:
    out += [
        "Each row is a control that claims this standard on the board. The artifact that",
        "proves it is named in the story; this index does not assert coverage.",
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
