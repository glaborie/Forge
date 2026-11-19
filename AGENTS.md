# Forge

This file tells coding agents (Claude Code, Cursor, Codex, Copilot Workspace, etc.) how to work in this repository. It describes the project, the script contracts, the environment they require, and the API gotchas that will otherwise waste your time.

1. What this repository is
Three artifacts live together here:

MATRIX.md — the vendor-neutral framework document defining the four reliability dimensions (Functional, Security, Operational, Temporal), their metrics and SLO thresholds, and their mapping to NIST AI RMF, ISO/IEC 42001, ISO/IEC 42119‑8, OWASP LLM Top 10, CSA AICM, ENISA FAICP, and the EU AI Act.

standard-index.json — the machine-readable standard registry and story→standard index. Authoritative for tooling; MATRIX.md §8 mirrors it for readers. Its `Standard` identifiers are the exact values the project's `Standard` field must contain.

scripts/ — a small Bash + Python toolchain that materializes the matrix as a GitHub Projects V2 backlog and keeps it consistent as work progresses.

The scripts are the operational half. They are not demos; they are the actual mechanism by which the backlog is created, triaged, and dependency-managed. If you change a script, you must update this file and the corresponding section of the matrix document.

2. File map
text
.
├── AGENTS.md                       ← you are here
├── MATRIX.md                       ← framework doc
├── standard-index.json             ← standard registry + story index
├── agentguard-backlog.csv          ← canonical backlog (32 items)
├── scripts/
│   ├── import-backlog.sh           ← CSV → GitHub Project (idempotent)
│   ├── triage-ready.sh             ← Backlog → Ready for P0s
│   ├── fetch-items.sh              ← GraphQL snapshot, flat JSON array
│   ├── block.sh                    ← set 'Blocked by' on an item
│   └── unblock.sh                  ← clear / sweep 'Blocked by'
└── .github/workflows/
    └── unblock-sweep.yml           ← scheduled or event-driven sweep
3. Prerequisites
Requirement	Why	How to verify
gh ≥ 2.40	project item-create, item-edit, field-list	gh --version
jq ≥ 1.6	All JSON handling	jq --version
python3 ≥ 3.8	CSV parsing (multiline bodies)	python3 --version
bash ≥ 4.4	Avoids ${#arr[@]} unbound-variable bug under set -u	bash --version
PAT with project scope	GITHUB_TOKEN cannot read or write Projects V2	gh auth status
If gh auth status does not list project:

bash
gh auth refresh -s project
Do not use GITHUB_TOKEN in CI for any script that touches Projects V2. A classic PAT stored as secrets.PROJECT_PAT is required.

4. Environment variables
All scripts accept positional arguments and fall back to these environment variables:

Variable	Default	Used by
PROJECT_NUM	5	all scripts
OWNER	@me	all scripts
DONE_STATUS	Done	unblock.sh --sweep
GH_TOKEN	from gh auth	CI only
Positional form is preferred for human use; environment form is preferred for CI and for agents running commands in a loop.

5. Script contracts
Treat these as stable interfaces. If you need to change a contract, update this file first.

5.1 import-backlog.sh
bash
./import-backlog.sh <csv-file> [project-num] [owner]
Input: CSV with header Title,Body,Labels,Dimension,Phase,Priority,Standard,Milestone,Epic.

Behavior: Creates every item that does not already exist by title; sets custom fields on items whether or not they were just created.

Idempotent: yes. Re-runs are safe.

Requires custom fields to exist in the target project: Dimension, Phase, Priority, Standard, Epic, Milestone (all SINGLE_SELECT or TEXT). Issue fields are silently skipped with a warning.

Exit codes: 0 success, 1 on missing file / unresolved project / field-schema mismatch.

5.2 triage-ready.sh
bash
./triage-ready.sh [project-num] [owner] [from-status] [to-status] [priority]
Defaults: 5 @me Backlog Ready P0.

Behavior: Moves every item currently in from-status whose Priority equals priority to to-status.

Idempotent: yes. Second run matches zero items.

Exit codes: 0 success (including zero matches), 1 on field/option missing.

5.3 fetch-items.sh
bash
./fetch-items.sh [project-num] [owner]
Output: a top-level JSON array of flat objects: { id, title, status, priority, dimension, phase, standard, epic, milestone, blockedby, … }.

Includes every custom field, including Blocked by — which gh project item-list --format json omits.

Never pipe this through .items[]. The root is .[], not .items[]. This is the single most common bug.

Do not replace this with gh project item-list. The two flags --field and --format json are mutually exclusive, which is exactly why this script exists.

Exit codes: 0 success, 1 on unresolvable project or missing token scope.

5.4 block.sh
bash
./block.sh --setup
./block.sh <target> <blocker1> [<blocker2> …]
./block.sh --from-csv <file>          # optional, see §8
--setup: idempotently creates the Blocked by custom text field.

Target and blocker arguments: exact title, or a unique prefix ("A1.", "D1. Deploy"). Ambiguous prefixes are rejected with a list of candidates.

Behavior: Writes the semicolon-joined blocker titles into Blocked by on the target item. Replaces any existing value.

Exit codes: 0 success, 1 on ambiguity, missing item, or missing field.

5.5 unblock.sh
bash
./unblock.sh <target>
./unblock.sh --sweep [--dry-run]
Single mode: clears Blocked by on one item.

--sweep: for every item whose Blocked by is non-empty, parses each blocker title, looks up its Status, and clears Blocked by only if all blockers equal $DONE_STATUS.

--dry-run: prints the decision tree (UNBLOCK / WOULD UNBLOCK / per-blocker status) without writing.

Idempotent: yes. Safe to run on a cron.

Exit codes: 0 success, 1 on unresolved target or missing field.

6. Known API gotchas
Each of these has already cost time in this repository. Do not re-discover them.

Symptom	Cause	Fix
Cannot index array with string "items"	Script written against old gh project item-list shape {items:…}; fetch-items.sh returns a bare array.	Use .[], not .items[]. If sed-ing, exclude fetch-items.sh.
--field cannot be used with --id	CLI rejects mixed addressing modes.	Use --field-id + --project-id + --id, and a type-specific value flag (--single-select-option-id or --text). --value is name-mode only.
Issue field values cannot be updated using updateProjectV2ItemFieldValue	The field is an issue field, not a custom project field.	Recreate the field via gh project field-create (goes into the "Custom fields" bucket). Issue fields cannot be written through the project API.
--format json rejected together with --field	Mutually exclusive on gh project item-list.	Use fetch-items.sh (GraphQL).
@me unusable in GraphQL	It is a CLI alias, not a login.	OWNER=$(gh api user --jq .login) before any GraphQL call.
Could not resolve to a ProjectV2	Trying node(id: owner) { ... on User { projectV2(…) } }.	Query user(login: …) { projectV2(number: …) } or organization(login: …) { … } directly.
EXISTING_TITLES: unbound variable	Bash ≤ 4.3 with set -u and ${#empty_assoc[@]}.	Do not use ${#arr[@]} for emptiness; use jq 'length' on exported JSON, or require Bash ≥ 4.4.
Options truncated at first comma	--single-select-options splits on ,.	Keep option labels comma-free. Store the full title in the item body.
Draft items have no labels	GitHub limitation on ProjectV2DraftIssue.	Append _Labels: …_ to the item body (the importer already does this).
7. Canonical workflows for agents
7.1 Rebuilding the entire board from scratch
bash
# Field setup (once per project)
gh project field-create 5 --owner @me --name "Dimension" --data-type SINGLE_SELECT \
  --single-select-options "Functional,Security,Operational,Temporal,Cross-cutting"
gh project field-create 5 --owner @me --name "Phase" --data-type SINGLE_SELECT \
  --single-select-options "Baseline,Guardrails,Evaluation,Red Teaming,Continuous Improvement"
gh project field-create 5 --owner @me --name "Priority" --data-type SINGLE_SELECT \
  --single-select-options "P0,P1,P2"
gh project field-create 5 --owner @me --name "Standard" --data-type TEXT
gh project field-create 5 --owner @me --name "Epic" --data-type SINGLE_SELECT \
  --single-select-options "Epic A,Epic B,Epic C,Epic D,Epic E,Epic F,Epic G"
gh project field-create 5 --owner @me --name "Milestone" --data-type SINGLE_SELECT \
  --single-select-options "M1 Baseline,M2 Guardrails,M3 Evaluation,M4 Red Teaming,M5 Continuous Improvement"
./block.sh --setup

# Populate
./import-backlog.sh agentguard-backlog.csv 5 @me

# Triage
./triage-ready.sh 5 @me Backlog Ready P0

# Dependencies (see §8 for CSV-driven mode)
./block.sh "A2. Create operational reliability dashboard" "A1. Instrument AI requests with OpenTelemetry"
./block.sh "B3. Run regression suite on model/prompt changes" "B1. Create and import golden datasets"
./block.sh "C3. Add functional evaluation gate to CI" "C1. Configure LLM-as-judge evaluators"
./block.sh "D3. Run automated adversarial tests in CI" \
  "D1. Deploy input guardrails for prompt injection and system-prompt leakage" \
  "D2. Deploy output guardrails for PII and unsafe content"
./block.sh "F1. Detect input and embedding drift" \
  "A1. Instrument AI requests with OpenTelemetry" \
  "A2. Create operational reliability dashboard"
./block.sh "B2. Turn production failures into golden-dataset candidates" \
  "B1. Create and import golden datasets" \
  "C1. Configure LLM-as-judge evaluators"
./block.sh "E1. Add circuit breakers and fallback behavior" \
  "A1. Instrument AI requests with OpenTelemetry"
Every step is idempotent. Re-running the block is safe and does not duplicate anything.

7.2 Daily standup check
bash
./unblock.sh --sweep --dry-run
./fetch-items.sh 5 @me | jq -r '
  .[] | select(.status == "Ready" and (.blockedby // "") == "")
      | [.priority, .title] | @tsv' | sort
The first command tells you which items would auto-unblock today. The second lists every workable item in Ready (excluding blocked ones) — that is the sprint candidate set.

7.3 Closing out a blocker
When A1 moves to Done:

bash
./unblock.sh --sweep
A2, E1, and F1 (if A2 is also Done) lose their Blocked by value automatically. They remain in Backlog until someone moves them to Ready — the sweep is deliberately conservative and never promotes items across the Backlog→Ready boundary.

8. Optional: reproducible dependency graph from CSV
If block.sh has been extended with --from-csv (see the matrix doc for the patch), the dependency graph lives in agentguard-backlog.csv under a Blocked by column, and:

bash
./block.sh --from-csv agentguard-backlog.csv
rebuilds the entire graph in one call. Prefer this over the seven individual block.sh calls once the feature exists — it makes the CSV the single source of truth for both content and dependencies.

9. Conventions for agents editing this repo
Never edit files inside .github/, scripts/, or AGENTS.md without updating the corresponding section here. Agents that leave the documentation stale cause more damage than agents that leave code buggy.

Prefer ./fetch-items.sh over gh project item-list in any new script. The --field / --format conflict will bite the moment you need a custom field.

Never assume .items[]. fetch-items.sh returns .[]. This is the single largest class of bug in this repo.

Never mix --field and --id. Pick one addressing mode per gh call.

Never write to an issue field. If gh returns "Issue field values cannot be updated using updateProjectV2ItemFieldValue", recreate the field via gh project field-create. Do not try to work around it.

Guard against Bash version drift. Any use of ${#arr[@]} under set -u is a bug on macOS. Either require Bash 4.4 or use jq 'length'.

CSV is the source of truth. Scripts derive state from agentguard-backlog.csv and the project; the project should never contain items that are not in the CSV.

Idempotency is a hard requirement. Every script must be safe to run twice in a row. This is the invariant that makes the whole pipeline usable in CI.

10. When you get stuck
If a script fails, run it under bash -xv first. The last two lines of trace plus the failing gh or jq command almost always identify the issue by inspection.

If fetch-items.sh returns an empty array but the UI shows items:

gh auth status — confirm project scope.

Re-derive the project ID: gh project list --owner @me --format json.

Confirm the owner: an org-owned project cannot be resolved through user(login:).

If a jq filter returns zero rows but the field is visibly populated in the UI:

./fetch-items.sh 5 @me | jq '.[0] | keys' — confirm the sanitized key name (Blocked by → blockedby).

The sanitizer is ascii_downcase | gsub("[^a-z0-9]"; "") — a field with a punctuation character will produce a key you did not anticipate. Use the actual key.

If you are still stuck, open an issue titled agent: <script> — <symptom> and include the full bash -xv trace plus gh auth status output.