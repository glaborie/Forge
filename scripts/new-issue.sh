#!/usr/bin/env bash
# Create a story on the board with every field set, attached to its epic, and
# validated. One command instead of ten gh calls that are easy to get wrong.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_NUM="${PROJECT_NUM:-5}"
OWNER="${OWNER:-@me}"
REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

usage() {
  cat >&2 <<'EOF'
Usage: new-issue.sh --title TITLE --body-file FILE --dimension D --phase P \
                    --priority P0|P1|P2|P3 --standard STD --milestone M --epic "Epic X" \
                    [--labels story,compliance] [--dry-run]

  --standard accepts MATRIX.md §8 identifiers joined by "; ", or N/A.
  --epic is matched by title prefix: "Epic A", "Epic B", …
  --body-file avoids shell quoting on multi-line bodies.
EOF
  exit 1
}

TITLE="" BODY_FILE="" DIMENSION="" PHASE="" PRIORITY="" STANDARD="" MILESTONE="" EPIC=""
LABELS="" DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --title) TITLE="$2"; shift 2 ;;
    --body-file) BODY_FILE="$2"; shift 2 ;;
    --dimension) DIMENSION="$2"; shift 2 ;;
    --phase) PHASE="$2"; shift 2 ;;
    --priority) PRIORITY="$2"; shift 2 ;;
    --standard) STANDARD="$2"; shift 2 ;;
    --milestone) MILESTONE="$2"; shift 2 ;;
    --epic) EPIC="$2"; shift 2 ;;
    --labels) LABELS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown argument: $1" >&2; usage ;;
  esac
done

for required in TITLE BODY_FILE DIMENSION PHASE PRIORITY STANDARD MILESTONE EPIC; do
  [[ -n "${!required}" ]] || { echo "missing --$(echo "$required" | tr '[:upper:]_' '[:lower:]-')" >&2; usage; }
done
[[ -f "$BODY_FILE" ]] || { echo "no such body file: $BODY_FILE" >&2; exit 1; }

# Vocabulary in one place: MATRIX.md §8 plus the sentinel for framework-internal work.
python3 - "$DIMENSION" "$PHASE" "$PRIORITY" "$STANDARD" <<'PY'
import sys
dimension, phase, priority, standard = sys.argv[1:5]
allowed = {
    "dimension": {"Functional", "Security", "Operational", "Temporal", "Cross-cutting"},
    "phase": {"Baseline", "Guardrails", "Evaluation", "Red Teaming", "Continuous Improvement"},
    "priority": {"P0", "P1", "P2", "P3"},
    "standard": {
        "NIST AI RMF", "NIST AI 800-3", "ISO/IEC 42001", "ISO/IEC 42119-8",
        "OWASP LLM Top 10", "Google SAIF", "CSA AICM", "ENISA FAICP", "EU AI Act", "N/A",
    },
}
problems = [f"{name}={value!r} not allowed" for name, value in
            (("dimension", dimension), ("phase", phase), ("priority", priority))
            if value not in allowed[name]]
problems += [f"standard={token.strip()!r} not allowed"
             for token in standard.split(";") if token.strip() not in allowed["standard"]]
if problems:
    sys.exit("\n".join(problems))
PY

LOGIN="$(gh api user --jq .login)"
PROJECT_ID="$(gh api graphql -f query='query { user(login:"'"$LOGIN"'"){ projectV2(number:'"$PROJECT_NUM"'){ id } } }' \
  --jq '.data.user.projectV2.id')"
FIELDS=$(gh project field-list "$PROJECT_NUM" --owner "$OWNER" --format json)
field_id() { echo "$FIELDS" | jq -r --arg n "$1" '.fields[]|select(.name==$n)|.id'; }
option_id() { echo "$FIELDS" | jq -r --arg n "$1" --arg o "$2" \
  '.fields[]|select(.name==$n)|.options[]|select(.name==$o)|.id'; }

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "would create: $TITLE"
  echo "  labels=$LABELS dimension=$DIMENSION phase=$PHASE priority=$PRIORITY"
  echo "  standard=$STANDARD milestone=$MILESTONE epic=$EPIC"
  exit 0
fi

cmd=(gh issue create --repo "$REPO" --title "$TITLE" --body-file "$BODY_FILE")
[[ -n "$LABELS" ]] && cmd+=(--label "$LABELS")
URL="$("${cmd[@]}" | tail -1)"
NUMBER="${URL##*/}"
echo "created #$NUMBER $URL"

# The project's built-in auto-add workflow races us; look the item up instead.
ITEM=""
for _ in $(seq 1 20); do
  ITEM="$(gh api graphql -f query='query { user(login:"'"$LOGIN"'"){ projectV2(number:'"$PROJECT_NUM"'){ items(first:100){ nodes { id content { ... on Issue { number } } } } } } }' \
    --jq '[.data.user.projectV2.items.nodes[] | select(.content.number=='"$NUMBER"') | .id] | first // empty' 2>/dev/null || true)"
  [[ -n "$ITEM" ]] && break
  sleep 1
done
if [[ -z "$ITEM" ]]; then
  echo "auto-add did not claim #$NUMBER; adding it explicitly" >&2
  ITEM="$(gh project item-add "$PROJECT_NUM" --owner "$OWNER" --url "$URL" --format json | jq -r .id)"
fi

for pair in "Dimension:$DIMENSION" "Phase:$PHASE" "Priority:$PRIORITY"; do
  name="${pair%%:*}"; value="${pair#*:}"
  gh project item-edit --id "$ITEM" --project-id "$PROJECT_ID" \
    --field-id "$(field_id "$name")" --single-select-option-id "$(option_id "$name" "$value")" >/dev/null
done
gh project item-edit --id "$ITEM" --project-id "$PROJECT_ID" \
  --field-id "$(field_id Standard)" --text "$STANDARD" >/dev/null

gh issue edit "$NUMBER" --repo "$REPO" --milestone "$MILESTONE" >/dev/null

EPIC_NUMBER="$(gh issue list --repo "$REPO" --state all --limit 200 --json number,title \
  --jq '[.[]|select(.title|startswith("'"$EPIC"'"))]|first|.number // empty')"
[[ -n "$EPIC_NUMBER" ]] || { echo "no epic matching '$EPIC'" >&2; exit 1; }
gh api graphql -f query='mutation($p:ID!,$c:ID!){addSubIssue(input:{issueId:$p,subIssueId:$c}){issue{number}}}' \
  -f p="$(gh issue view "$EPIC_NUMBER" --repo "$REPO" --json id --jq .id)" \
  -f c="$(gh issue view "$NUMBER" --repo "$REPO" --json id --jq .id)" >/dev/null

"$ROOT/scripts/validate-project.sh" "$PROJECT_NUM" "$OWNER"
echo "#$NUMBER ready: $TITLE"
