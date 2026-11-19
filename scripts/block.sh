#!/usr/bin/env bash
# Set native "blocked by" relations on a story. Titles, or unique prefixes.
#
#   ./block.sh "A2. Create operational reliability dashboard" "A1. Instrument AI requests"
#   ./block.sh A2 A1 E1
#
# Exit codes: 0 success, 1 on ambiguity or unresolved title.
set -euo pipefail

REPO="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

if [[ $# -lt 2 ]]; then
  echo "usage: ./block.sh <target> <blocker1> [<blocker2> ...]" >&2
  exit 1
fi

TARGET="$1"
shift

TITLES=$(
  gh issue list --repo "$REPO" --state all --limit 500 --json number,title
)

python3 - "$REPO" "$TARGET" "$@" <<PY
import json, subprocess, sys

repo, target, blockers = sys.argv[1], sys.argv[2], sys.argv[3:]
issues = json.loads('''$TITLES''')


def resolve(query):
    exact = [i for i in issues if i["title"] == query]
    if exact:
        return exact[0]
    matches = [i for i in issues if i["title"].startswith(query)]
    if not matches:
        sys.exit(f"no issue matches {query!r}")
    if len(matches) > 1:
        listing = "\n  ".join(f'#{i["number"]} {i["title"]}' for i in matches)
        sys.exit(f"{query!r} is ambiguous:\n  {listing}")
    return matches[0]


t = resolve(target)
b = [resolve(q) for q in blockers]
nums = ",".join(str(i["number"]) for i in b)
subprocess.run(["gh", "issue", "edit", str(t["number"]), "--repo", repo,
                "--add-blocked-by", nums], check=True)
print(f"#{t['number']} blocked by " + ", ".join(f"#{i['number']}" for i in b))
PY
