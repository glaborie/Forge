#!/usr/bin/env bash
# Validate that project 5 is internally consistent. Exits non-zero on drift.
# The project is the source of truth; this is the gate that keeps it that way.
set -euo pipefail

PROJECT_NUM="${1:-5}"
OWNER="${2:-@me}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

ITEMS="$("$ROOT/scripts/fetch-items.sh" "$PROJECT_NUM" "$OWNER")"

python3 - "$ITEMS" <<'PY'
import json
import sys

items = json.loads(sys.argv[1])
# Pull requests are auto-added to the project too; they are not stories and carry
# no Dimension/Phase/Priority. Only issues are validated.
items = [i for i in items if i.get("type") == "Issue"]
# The nine identifiers from MATRIX.md section 8. Update both together.
# "N/A" is the documented sentinel for framework-internal stories with no
# external standard (G3 carries a score, not a compliance claim).
STANDARDS = {
    "NIST AI RMF", "NIST AI 800-3", "ISO/IEC 42001", "ISO/IEC 42119-8",
    "OWASP LLM Top 10", "Google SAIF", "CSA AICM", "ENISA FAICP", "EU AI Act",
    "N/A",
}
DIMENSIONS = {"Functional", "Security", "Operational", "Temporal", "Cross-cutting"}
PHASES = {"Baseline", "Guardrails", "Evaluation", "Red Teaming", "Continuous Improvement"}
PRIORITIES = {"P0", "P1", "P2", "P3"}
STATUSES = {"Backlog", "Ready", "In progress", "Done", "Tracking"}

errors: list[str] = []
titles = [i["title"] for i in items]
epics = {i["title"] for i in items if i["title"].startswith("Epic ")}
stories = [i for i in items if not i["title"].startswith("Epic ")]

# A token with only `read:project` can read items and fields but not issue
# relations, which come back null instead of erroring. Say so plainly rather
# than emitting one "no parent epic" per story.
if stories and epics and not any(i.get("epic") for i in stories):
    print(
        "error: no story reports a parent epic, so the issues' relations are not visible.\n"
        "       The token needs the classic 'repo' scope as well as 'read:project':\n"
        "       'read:project' alone reads the project but returns null for parent and blockedBy.",
        file=sys.stderr,
    )
    sys.exit(1)


def check(item, field, allowed, required=True):
    value = (item.get(field) or "").strip()
    if not value:
        if required:
            errors.append(f'{item["title"]}: missing {field}')
        return
    if field == "standard":
        unknown = [v.strip() for v in value.split(";") if v.strip() not in allowed]
    else:
        unknown = [value] if value not in allowed else []
    for bad in unknown:
        errors.append(f'{item["title"]}: {field}={bad!r} not in the allowed set')


for item in items:
    if not item["title"]:
        errors.append(f'{item["id"]}: item has no title')
    check(item, "dimension", DIMENSIONS)
    check(item, "phase", PHASES)
    check(item, "priority", PRIORITIES)
    check(item, "standard", STANDARDS)
    check(item, "status", STATUSES)

    if item["title"].startswith("Epic "):
        if item.get("status") != "Tracking":
            errors.append(f'{item["title"]}: epic must be Tracking, is {item.get("status")!r}')
    else:
        if not item.get("epic"):
            errors.append(f'{item["title"]}: story has no parent epic')
        elif item["epic"] not in epics:
            errors.append(f'{item["title"]}: parent epic {item["epic"]!r} is not an item in this project')

for title in {t for t in titles if titles.count(t) > 1}:
    errors.append(f"duplicate title: {title}")

for item in items:
    for blocker in filter(None, (b.strip() for b in (item.get("blockedby") or "").split(";"))):
        if blocker not in titles:
            errors.append(f'{item["title"]}: blocked by {blocker!r}, which is not an item in this project')

if errors:
    print(f"{len(errors)} problem(s):", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    sys.exit(1)

print(f"OK: {len(items)} items, {len(epics)} epics, no drift")
PY
