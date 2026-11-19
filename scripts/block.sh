#!/usr/bin/env bash
set -euo pipefail

PROJECT_NUM="${PROJECT_NUM:-5}"
OWNER="${OWNER:-@me}"
SEP=';'

if [[ "${1:-}" == "--setup" ]]; then
  if gh project field-list "$PROJECT_NUM" --owner "$OWNER" --format json \
       | jq -e '.fields[]|select(.name=="Blocked by")' >/dev/null; then
    echo "Field 'Blocked by' already exists."
  else
    gh project field-create "$PROJECT_NUM" --owner "$OWNER" \
      --name "Blocked by" --data-type TEXT
    echo "Created text field 'Blocked by'."
  fi
  exit 0
fi

if [[ $# -lt 2 ]]; then
  cat >&2 <<EOF
Usage: $0 <target> <blocker1> [<blocker2> ...]
       $0 --setup

Sets 'Blocked by' on <target> to the semicolon-joined titles of the blockers.
Titles may be exact strings or unique prefixes (e.g. 'B1.', 'D1. Deploy').

Env: PROJECT_NUM (default 5), OWNER (default @me)
EOF
  exit 1
fi

TARGET_QUERY="$1"; shift
BLOCKER_QUERIES=("$@")

PROJECT_ID=$(gh project list --owner "$OWNER" --format json \
  | jq -r --argjson n "$PROJECT_NUM" '.projects[]|select(.number==$n)|.id')
[[ -n "$PROJECT_ID" ]] || { echo "Project #$PROJECT_NUM not found" >&2; exit 1; }

BLOCKED_BY_ID=$(gh project field-list "$PROJECT_NUM" --owner "$OWNER" --format json \
  | jq -r '.fields[]|select(.name=="Blocked by")|.id')
[[ -n "$BLOCKED_BY_ID" && "$BLOCKED_BY_ID" != "null" ]] || {
  echo "Field 'Blocked by' missing. Run: $0 --setup" >&2; exit 1; }

ITEMS_JSON=$(mktemp)
trap 'rm -f "$ITEMS_JSON"' EXIT
./fetch-items.sh "$PROJECT_NUM" "$OWNER" > "$ITEMS_JSON"

# Assert fetch-items.sh emitted the expected shape
if ! jq -e 'type == "array"' "$ITEMS_JSON" >/dev/null 2>&1; then
  echo "ERROR: $ITEMS_JSON is not a top-level array." >&2
  echo "This script expects output from ./fetch-items.sh, not 'gh project item-list'." >&2
  exit 1
fi

resolve() {
  local q="$1"
  if [[ -z "$q" ]]; then echo "ERROR: empty query" >&2; return 1; fi
  local count
  count=$(jq --arg q "$q" \
    '[.[] | select(.title == $q or (.title|startswith($q)))] | length' \
    "$ITEMS_JSON")
  if [[ "$count" == "0" ]]; then
    echo "ERROR: no item matches '$q'" >&2; return 1
  fi
  if [[ "$count" -gt 1 ]]; then
    echo "ERROR: '$q' matches $count items:" >&2
    jq -r --arg q "$q" \
      '.[] | select(.title == $q or (.title|startswith($q))) | "  - " + .title' \
      "$ITEMS_JSON" >&2
    return 1
  fi
  jq -r --arg q "$q" \
    '.[] | select(.title == $q or (.title|startswith($q))) | .id' \
    "$ITEMS_JSON"
}

TARGET_ID=$(resolve "$TARGET_QUERY")
TARGET_TITLE=$(jq -r --arg id "$TARGET_ID" '.[]|select(.id==$id)|.title' "$ITEMS_JSON")

BLOCKER_TITLES=()
for q in "${BLOCKER_QUERIES[@]}"; do
  bid=$(resolve "$q")
  btitle=$(jq -r --arg id "$bid" '.[]|select(.id==$id)|.title' "$ITEMS_JSON")
  BLOCKER_TITLES+=("$btitle")
done

JOINED=$(IFS="$SEP"; echo "${BLOCKER_TITLES[*]}")

echo "Target:     $TARGET_TITLE"
echo "Blocked by: $JOINED"

gh project item-edit \
  --id "$TARGET_ID" \
  --field-id "$BLOCKED_BY_ID" \
  --project-id "$PROJECT_ID" \
  --text "$JOINED" >/dev/null

echo "Updated."
