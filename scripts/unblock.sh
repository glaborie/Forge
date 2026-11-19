#!/usr/bin/env bash
set -euo pipefail

PROJECT_NUM="${PROJECT_NUM:-5}"
OWNER="${OWNER:-@me}"
SEP=';'
DONE_STATUS="${DONE_STATUS:-Done}"

usage() {
  cat >&2 <<EOF
Usage: $0 <target>              # clear Blocked by on one item
       $0 --sweep [--dry-run]   # auto-clear where all blockers are '$DONE_STATUS'

Env: PROJECT_NUM (default 5), OWNER (default @me), DONE_STATUS (default Done)
EOF
  exit 1
}

[[ $# -ge 1 ]] || usage

PROJECT_ID=$(gh project list --owner "$OWNER" --format json \
  | jq -r --argjson n "$PROJECT_NUM" '.projects[]|select(.number==$n)|.id')
[[ -n "$PROJECT_ID" ]] || { echo "Project #$PROJECT_NUM not found" >&2; exit 1; }

BLOCKED_BY_ID=$(gh project field-list "$PROJECT_NUM" --owner "$OWNER" --format json \
  | jq -r '.fields[]|select(.name=="Blocked by")|.id')
[[ -n "$BLOCKED_BY_ID" && "$BLOCKED_BY_ID" != "null" ]] || {
  echo "Field 'Blocked by' missing. Run: ./block.sh --setup" >&2; exit 1; }

ITEMS_JSON=$(mktemp)
trap 'rm -f "$ITEMS_JSON"' EXIT
./fetch-items.sh "$PROJECT_NUM" "$OWNER" > "$ITEMS_JSON"

# Assert fetch-items.sh emitted the expected shape
if ! jq -e 'type == "array"' "$ITEMS_JSON" >/dev/null 2>&1; then
  echo "ERROR: $ITEMS_JSON is not a top-level array." >&2
  echo "This script expects output from ./fetch-items.sh, not 'gh project item-list'." >&2
  exit 1
fi

clear_field() {
  local id="$1"
  gh project item-edit \
    --id "$id" \
    --field-id "$BLOCKED_BY_ID" \
    --project-id "$PROJECT_ID" \
    --text "" >/dev/null
}

case "$1" in
  --sweep)
    DRY_RUN=false
    [[ "${2:-}" == "--dry-run" ]] && DRY_RUN=true

    # Emit "<id>\t<title>\t<blockedby>" for every blocked item
    while IFS=$'\t' read -r item_id item_title blockers; do
      all_done=true
      IFS="$SEP" read -ra arr <<< "$blockers"
      for b in "${arr[@]}"; do
        b_trim=$(sed 's/^ *//;s/ *$//' <<< "$b")
        status=$(jq -r --arg t "$b_trim" \
          '.[]|select(.title==$t)|.status // "MISSING"' "$ITEMS_JSON")
        printf '  %-40.40s  blocked by  %-40.40s  [%s]\n' \
          "$item_title" "$b_trim" "$status"
        [[ "$status" == "$DONE_STATUS" ]] || all_done=false
      done

      if $all_done; then
        if $DRY_RUN; then
          echo "  WOULD UNBLOCK: $item_title"
        else
          echo "  UNBLOCK: $item_title"
          clear_field "$item_id"
        fi
      fi
      echo
    done < <(jq -r '.[] | select((.blockedby // "") != "")
                     | [.id, .title, .blockedby] | @tsv' "$ITEMS_JSON")
    ;;

  *)
    TARGET_QUERY="$1"
    TARGET_ID=$(jq -r --arg q "$TARGET_QUERY" '
      [.[] | select(.title == $q or (.title|startswith($q)))]
      | if length == 0 then "MISSING"
        elif length > 1 then "AMBIGUOUS"
        else (.[0].id) end' "$ITEMS_JSON")

    if [[ "$TARGET_ID" == "MISSING" ]]; then
      echo "ERROR: no item matches '$TARGET_QUERY'" >&2; exit 1
    fi
    if [[ "$TARGET_ID" == "AMBIGUOUS" ]]; then
      echo "ERROR: '$TARGET_QUERY' matches more than one item:" >&2
      jq -r --arg q "$TARGET_QUERY" '
        .[] | select(.title == $q or (.title|startswith($q))) | "  - " + .title' \
        "$ITEMS_JSON" >&2
      exit 1
    fi

    TITLE=$(jq -r --arg id "$TARGET_ID" '.[]|select(.id==$id)|.title' "$ITEMS_JSON")
    echo "Clearing 'Blocked by' on: $TITLE"
    clear_field "$TARGET_ID"
    echo "Done."
    ;;
esac
