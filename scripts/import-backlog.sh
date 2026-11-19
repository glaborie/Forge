#!/usr/bin/env bash
set -euo pipefail

CSV_FILE="${1:-agentguard-backlog.csv}"
PROJECT_NUM="${2:-1}"
OWNER="${3:-@me}"

[[ -f "$CSV_FILE" ]] || { echo "Missing CSV: $CSV_FILE" >&2; exit 1; }

PROJECT_ID=$(gh project list --owner "$OWNER" --format json \
  | jq -r --argjson num "$PROJECT_NUM" '.projects[] | select(.number == $num) | .id')
[[ -n "$PROJECT_ID" ]] || { echo "Project #$PROJECT_NUM not found" >&2; exit 1; }

# ---- Field schema: name -> {id, options, isCustom} ----
FIELD_SCHEMA=$(gh project field-list "$PROJECT_NUM" --owner "$OWNER" --format json \
  | jq -c '
      [.fields[]
       | {
           (.name): {
             id: .id,
             options: ((.options // []) | map({name, id})),
             isCustom: (.id | startswith("PVTSSF_") or startswith("PVTF_") or startswith("PVTSSO_"))
           }
         }
      ] | add // {}')
export FIELD_SCHEMA

EXISTING_MAP=$(gh project item-list "$PROJECT_NUM" --owner "$OWNER" --format json --limit 1000 \
  | jq -c '[.items[] | select(.title != null and .title != "") | {(.title): .id}] | add // {}')
export EXISTING_MAP

export PROJECT_ID PROJECT_NUM OWNER

python3 - "$CSV_FILE" <<'PY'
import csv, json, os, subprocess, sys

csv_file = sys.argv[1]

def gh(args):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

SCHEMA   = json.loads(os.environ["FIELD_SCHEMA"])
EXISTING = json.loads(os.environ["EXISTING_MAP"])
PROJECT_ID  = os.environ["PROJECT_ID"]
PROJECT_NUM = os.environ["PROJECT_NUM"]
OWNER       = os.environ["OWNER"]

COL_TO_FIELD = {
    "Dimension": "Dimension",
    "Phase":     "Phase",
    "Priority":  "Priority",
    "Standard":  "Standard",
    "Epic":      "Epic",
}

with open(csv_file, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

total = len(rows)
for idx, row in enumerate(rows, start=1):
    title = (row.get("Title") or "").strip()
    if not title:
        continue

    body = (row.get("Body") or "").strip()
    labels = (row.get("Labels") or "").strip()
    if labels:
        body += f"\n\n_Labels: {labels}_"

    if title in EXISTING:
        item_id = EXISTING[title]
        print(f"[{idx}/{total}] EXISTS: {title}")
    else:
        print(f"[{idx}/{total}] CREATE: {title}")
        rc, out, err = gh(["project","item-create",PROJECT_NUM,"--owner",OWNER,
                           "--title",title,"--body",body,"--format","json"])
        if rc != 0:
            print(f"  ! create failed: {err}", file=sys.stderr)
            continue
        item_id = json.loads(out)["id"]

    for col, field_name in COL_TO_FIELD.items():
        val = (row.get(col) or "").strip()
        if not val:
            continue

        info = SCHEMA.get(field_name)
        if not info:
            print(f"  ? field '{field_name}' not in project; skip", file=sys.stderr)
            continue

        if not info["isCustom"]:
            print(f"  ⚠ '{field_name}' is an issue field; cannot set via project item. "
                  f"Convert it to a custom project field first.", file=sys.stderr)
            continue

        base = ["project","item-edit","--id",item_id,
                "--field-id",info["id"],"--project-id",PROJECT_ID]

        if info["options"]:
            # single-select: resolve label -> option node ID
            match = next((o for o in info["options"] if o["name"] == val), None)
            if not match:
                print(f"  ! option '{val}' not found for '{field_name}'", file=sys.stderr)
                continue
            args = base + ["--single-select-option-id", match["id"]]
        else:
            # text (or number/date if you extend this branch)
            args = base + ["--text", val]

        rc, _, err = gh(args)
        if rc != 0:
            print(f"  ! set {field_name}='{val}' failed: {err}", file=sys.stderr)
        else:
            print(f"  set {field_name}: {val}")

print("Import complete.")
PY
