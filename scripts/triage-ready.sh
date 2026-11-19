#!/usr/bin/env bash
set -euo pipefail

PROJECT_NUM="${1:-5}"
OWNER="${2:-@me}"
FROM_STATUS="${3:-Backlog}"
TO_STATUS="${4:-Ready}"
PRIORITY="${5:-P0}"

# --- Project ID ---
PROJECT_ID=$(gh project list --owner "$OWNER" --format json \
  | jq -r --argjson n "$PROJECT_NUM" '.projects[]|select(.number==$n)|.id')
[[ -n "$PROJECT_ID" ]] || { echo "Project #$PROJECT_NUM not found" >&2; exit 1; }

# --- Status field + target option ID ---
STATUS_FIELD=$(gh project field-list "$PROJECT_NUM" --owner "$OWNER" --format json \
  | jq -c '.fields[]|select(.name=="Status")')
STATUS_ID=$(jq -r '.id' <<<"$STATUS_FIELD")
READY_OPT=$(jq -r --arg s "$TO_STATUS" \
  '.options[]|select(.name==$s)|.id' <<<"$STATUS_FIELD")
[[ -n "$STATUS_ID" && -n "$READY_OPT" && "$READY_OPT" != "null" ]] \
  || { echo "Status field or option '$TO_STATUS' missing" >&2; exit 1; }

echo "Status field: $STATUS_ID  -> option '$TO_STATUS': $READY_OPT"

# --- Collect IDs whose flat 'priority' key equals P0 (and optionally from FROM_STATUS) ---
mapfile -t IDS < <(
  gh project item-list "$PROJECT_NUM" --owner "$OWNER" --format json --limit 1000 \
  | jq -r --arg p "$PRIORITY" --arg f "$FROM_STATUS" '
      .items[]
      | select(.priority == $p)
      | select((.status // "") == $f or $f == "")
      | .id'
)

echo "Matched ${#IDS[@]} item(s) with priority=$PRIORITY and status=$FROM_STATUS"

if [[ ${#IDS[@]} -eq 0 ]]; then
  echo "Nothing to move. Check the diagnostic in the answer body." >&2
  exit 0
fi

for item_id in "${IDS[@]}"; do
  echo "Moving $item_id -> $TO_STATUS"
  gh project item-edit \
    --id "$item_id" \
    --field-id "$STATUS_ID" \
    --project-id "$PROJECT_ID" \
    --single-select-option-id "$READY_OPT" >/dev/null
done

echo "Done."
