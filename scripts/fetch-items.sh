#!/usr/bin/env bash
set -euo pipefail

PROJECT_NUM="${1:-5}"
OWNER_RAW="${2:-@me}"

# --- Resolve @me to a real login ---
if [[ "$OWNER_RAW" == "@me" || "$OWNER_RAW" == "me" ]]; then
  OWNER=$(gh api user --jq .login)
else
  OWNER="${OWNER_RAW#@}"
fi

# --- Resolve project node ID via direct lookup ---
# Try user first; fall back to organization.
PROJECT_ID=$(
  gh api graphql -f query='
    query($login: String!, $num: Int!) {
      user(login: $login) {
        projectV2(number: $num) { id }
      }
    }' -f login="$OWNER" -F num="$PROJECT_NUM" \
    --jq '.data.user.projectV2.id' 2>/dev/null || true
)

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "null" ]]; then
  PROJECT_ID=$(
    gh api graphql -f query='
      query($login: String!, $num: Int!) {
        organization(login: $login) {
          projectV2(number: $num) { id }
        }
      }' -f login="$OWNER" -F num="$PROJECT_NUM" \
      --jq '.data.organization.projectV2.id' 2>/dev/null || true
  )
fi

if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "null" ]]; then
  echo "Could not resolve project #$PROJECT_NUM for owner '$OWNER'." >&2
  echo "Check: project exists, token has 'project' scope (PAT), owner is correct." >&2
  exit 1
fi

# --- Fetch all items with field values, paginated ---
gh api graphql --paginate -f query='
  query($project: ID!, $cursor: String) {
    node(id: $project) {
      ... on ProjectV2 {
        items(first: 100, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            id
            content {
              ... on DraftIssue   { title }
              ... on Issue        { title }
              ... on PullRequest  { title }
            }
            fieldValues(first: 30) {
              nodes {
                ... on ProjectV2ItemFieldTextValue {
                  text
                  field { ... on ProjectV2FieldCommon { name } }
                }
                ... on ProjectV2ItemFieldSingleSelectValue {
                  name
                  field { ... on ProjectV2FieldCommon { name } }
                }
              }
            }
          }
        }
      }
    }
  }' -f project="$PROJECT_ID" \
  --jq '
    [.data.node.items.nodes[]
     | {
         id: .id,
         title: (.content.title // ""),
         fields: (
           .fieldValues.nodes
           | map(select(.field?.name != null) | {
               key: (.field.name | ascii_downcase | gsub("[^a-z0-9]"; "")),
               value: (.text // .name // "")
             })
           | from_entries
         )
       }
     | . + .fields
     | del(.fields)]
  '
