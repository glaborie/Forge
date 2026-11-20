# Forge

This file tells coding agents (Claude Code, Cursor, Codex, Copilot Workspace, etc.) how to work in this repository. It describes the project, the board schema, the script contracts, and the API gotchas that will otherwise waste your time.

1. What this repository is
Three artifacts live together here:

MATRIX.md — the vendor-neutral framework document defining the four reliability dimensions (Functional, Security, Operational, Temporal), their metrics and SLO thresholds, their standards mapping, and their mapping to the backlog.

src/forge_otel/ — the Python package that instruments an agent serving an OpenAI-compatible API. Contract in §6.5.

src/forge_audit/ — the append-only, hash-chained audit log for guardrail decisions. Contract in §6.7.

src/forge_guard/ — input guardrails for prompt injection and system-prompt leakage. Contract in §6.9.

src/forge_harness/ — injects a labelled corpus into a target and records both sides. Contract in §6.10.

scripts/ — a small Bash toolchain that reads, validates and triages the GitHub project. Not demos: they are how the board is inspected and moved.

The board itself is the fourth artifact and the one that matters most: **GitHub Project #5 for `glaborie` is the single source of truth for stories.** There is no CSV or JSON mirror. Stories are real issues in this repository, not draft items.

2. File map
text
.
├── AGENTS.md                       ← you are here
├── MATRIX.md                       ← framework doc
├── pyproject.toml                  ← Python package + tool config
├── src/forge_otel/                 ← A1 instrumentation package
├── src/forge_audit/                ← A3 audit log
├── src/forge_guard/                ← D1 input guardrails
├── src/forge_harness/              ← H1 inject / record / label
├── harness/corpus/                 ← labelled adversarial cases
├── tests/                          ← pytest suite + mock upstream
├── deploy/                         ← A2 stack: collector, Prometheus, Grafana
├── scripts/
│   ├── fetch-items.sh              ← GraphQL snapshot, flat JSON array
│   ├── validate-project.sh         ← board consistency gate
│   ├── new-issue.sh                ← create a story with every field set
│   ├── triage-ready.sh             ← Backlog → Ready for P0s
│   └── block.sh                    ← set native blocked-by relations
└── .github/workflows/
    ├── ci.yml                      ← ruff, mypy, pytest
    ├── project-automation.yml      ← branch naming → Status
    └── project-board.yml           ← branch naming → Status

3. Prerequisites
Requirement	Why	How to verify
gh ≥ 2.40	project, issue and GraphQL commands	gh --version
jq ≥ 1.6	All JSON handling	jq --version
python3 ≥ 3.8	CSV parsing in legacy helpers; validate-project.sh	python3 --version
bash ≥ 4.4	Avoids ${#arr[@]} unbound-variable bug under set -u	bash --version
uv ≥ 0.5	Python 3.12 + dependency management for forge_otel	uv --version
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
GH_TOKEN	from gh auth	CI only
FORGE_OTEL_ENDPOINT	unset	OTLP/HTTP collector endpoint; unset = spans created, nothing exported
FORGE_OTEL_CAPTURE_CONTENT	1	0 records prompt/completion sha256 instead of text
FORGE_OTEL_PRICES	unset	JSON price overrides, e.g. {"gpt-4o-mini": {"input": 0.15, "output": 0.60}} (USD per 1M tokens)
Positional form is preferred for human use; environment form is preferred for CI and for agents running commands in a loop.

The three `FORGE_OTEL_*` variables are read at call time, not import time.

5. Board schema
Everything the old CSV and standard-index.json carried now lives in the project or in GitHub's native issue features. Do not reintroduce a mirror.

5.1 Items and hierarchy
Epics are issues whose title starts with `Epic `. Stories are issues titled `<Letter><Number>. …` (e.g. `A1.`, `D3.`).

Stories are native **sub-issues** of their epic. The epic link is `.content.parent`; the "Epic" custom field no longer exists.

Milestones are native repository milestones: `M1 Baseline`, `M2 Guardrails`, `M3 Evaluation`, `M4 Red Teaming`, `M5 Continuous Improvement`. The custom Milestone field no longer exists.

Dependencies are native **blocked-by relations** (`gh issue edit --add-blocked-by`). The custom `Blocked by` field no longer exists.

Labels are native issue labels (`story`, `epic`, `observability`, `security`, `compliance`, `evaluation`, `guardrails`, `red-team`, `drift`). Draft bodies used to append `_Labels: …_`; that line is gone.

5.2 Custom fields
Only four, and only because GitHub has no native equivalent:

Field	Type	Values
Status	SINGLE_SELECT	Backlog, Ready, In progress, Done, Tracking
Priority	SINGLE_SELECT	P0, P1, P2, P3
Dimension	SINGLE_SELECT	Functional, Security, Operational, Temporal, Cross-cutting
Phase	SINGLE_SELECT	Baseline, Guardrails, Evaluation, Red Teaming, Continuous Improvement
Standard	TEXT	see below
Epics are always `Tracking`. Stories move `Backlog` → `Ready` → `In progress` → `Done`.

5.3 The Standard field
One or more framework identifiers, semicolon-separated, using the exact strings in MATRIX.md §8:

`NIST AI RMF`, `NIST AI 800-3`, `ISO/IEC 42001`, `ISO/IEC 42119-8`, `OWASP LLM Top 10`, `Google SAIF`, `CSA AICM`, `ENISA FAICP`, `EU AI Act`

`N/A` is the only other permitted value, for framework-internal stories that make no external compliance claim (currently `G3`). Control-level detail (`LLM01`, `Cl. 8`, `Art. 12`) belongs in MATRIX.md, never in this field — the field is for aggregation, not citation.

`scripts/validate-project.sh` hard-codes this list; change both together.

6. Script contracts
Treat these as stable interfaces. If you need to change a contract, update this file first.

6.1 fetch-items.sh
bash
./fetch-items.sh [project-num] [owner]
Output: a top-level JSON array of flat objects:

key	meaning
id	project item ID (PVTI_…)
type	Issue or PullRequest
title, number, url, state	issue identity
epic	parent issue title, or null
blockedby	`"; "`-joined titles of open and closed blockers, or ""
status, priority, dimension, phase, standard, milestone	field values, keyed by the sanitized field name
Never pipe this through `.items[]`. The root is `.[]`.

Do not replace this with `gh project item-list`. The two flags `--field` and `--format json` are mutually exclusive, which is exactly why this script exists.

Exit codes: 0 success, 1 on unresolvable project or missing token scope.

6.2 validate-project.sh
bash
./scripts/validate-project.sh [project-num] [owner]
Asserts that every item has a valid Dimension, Phase, Priority, Standard and Status; that epics are `Tracking`; that every story has a parent epic that exists in the project; that no title is duplicated; and that every blocked-by target is an item in the project.

Prints `OK: N items, M epics, no drift` and exits 0, or lists every problem and exits 1.

Run it before committing any board change, and after any script that writes to the project. It is the only thing standing between you and the drift that used to live in the CSV and the JSON.

CI runs it on every push and pull request to `main` using `secrets.PROJECT_PAT_RO`, which must carry **`repo` + `read:project`**. With `read:project` alone the project reads fine but every issue relation returns null, so the validator aborts with an explicit message rather than one "no parent epic" per story — that failure mode cost a CI cycle once. Fork PRs skip the step, because repository secrets are not exposed to them; the `if:` condition resolves the secret's presence into `env.HAS_PROJECT_PAT` at job level, since `secrets` cannot be used in an `if:` directly. Classic tokens have no read-only `repo` scope, so `PROJECT_PAT_RO` can still write issues — it is read-only *on the project*, not on the repository.

6.3 triage-ready.sh
bash
./triage-ready.sh [project-num] [owner] [from-status] [to-status] [priority]
Defaults: 5 @me Backlog Ready P0.

Moves every item in `from-status` whose Priority equals `priority` to `to-status`. Idempotent: a second run matches zero items.

6.4 block.sh
bash
./block.sh <target> <blocker1> [<blocker2> …]
Adds native blocked-by relations to <target>. Titles may be exact or a unique prefix (`A1.`, `D1. Deploy`); ambiguous prefixes are rejected with the candidate list.

To clear a relation: `gh issue edit <number> --remove-blocked-by <number>`. There is no sweep script, because GitHub now tracks whether a blocker is closed on its own.

6.5 forge_otel (Python package, not a script)
`pyproject.toml` defines one package, `forge_otel`, with two entry points:

`init_tracing(app, *, exporter=None, service_name="forge-agent")` — builds a `TracerProvider`, installs the inbound attribute middleware, and instruments FastAPI. Exports OTLP/HTTP when `FORGE_OTEL_ENDPOINT` is set or when an explicit `exporter` is passed; with neither, spans are created and dropped.

`llm_call(*, provider, model, prompt=None)` — context manager around the outbound provider call. Returns a handle whose `record_response(model=, input_tokens=, output_tokens=, completion=)` sets response model, token usage, content and cost. An exception inside the block sets span status ERROR and records the exception.

The span attributes are the contract A2, E1 and F1 consume; they are enumerated in issue #3 (story A1). Do not rename them without updating that issue and this section.

The same call also emits metrics, so dashboards never derive them from spans:

| Instrument | Type | Unit | Attributes |
| --- | --- | --- | --- |
| `gen_ai.client.operation.duration` | histogram | s | `gen_ai.request.model`, `gen_ai.operation.name`, `tenant.id` |
| `gen_ai.client.token.usage` | counter | {token} | + `gen_ai.token.type` = input/output |
| `forge.llm.cost.usd` | counter | — | `gen_ai.request.model`, `tenant.id` |
| `forge.llm.calls` | counter | {call} | + `error` = true/false |

`tenant.id` reaches the outbound call and its metrics through a `ContextVar` set by the inbound middleware, so callers never thread it through.

Tests run offline against `tests/fake_upstream.py`, an OpenAI-compatible FastAPI app, asserting on `InMemorySpanExporter`. No API key and no network are required: `uv run pytest`.

6.6 deploy/ (observability stack)
`./deploy/up.sh` starts a self-contained stack: the collector receives OTLP, forwards **traces to Langfuse Cloud** and exposes **metrics to Prometheus**, which Grafana reads. Ports are remapped off the defaults (`14317`/`14318`, `19090`, `13000`) so the stack does not collide with anything already running.

Credentials come from `.env` at the repo root or in `deploy/` (git-ignored); copy `deploy/.env.example`. Only Langfuse's own three variables are needed — `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` — and `up.sh` derives the `LANGFUSE_AUTH_STRING` (base64 of `public_key:secret_key`) and `LANGFUSE_OTLP_ENDPOINT` (`${LANGFUSE_BASE_URL}/api/public/otel`) that the collector reads. Langfuse accepts OTLP **HTTP only** — the gRPC receiver exists for other clients, not for Langfuse.

`gcx` (the Grafana CLI, ≥ 1.8) is the shortest path to inspecting the running stack, and it is agent-friendly: every command takes `--json`/`--jq`, `gcx commands` lists the surface, and `gcx docs` reads Grafana documentation.

```
gcx metrics query 'sum(forge_llm_calls_total)'   # PromQL without curl+jq
gcx datasources list                             # uid, url, readOnly
gcx dashboards list                              # provisioning metadata per dashboard
gcx dashboards get forge-reliability -o yaml     # export for diffing
```

A fresh machine needs a context, since the config is user-scoped and not in this repo:

```
gcx login local --server http://localhost:13000 --token <service-account-token>
```

On a headless host there is no OS keyring, so gcx refuses to store credentials until plaintext is allowed explicitly: run `gcx config set credentials.keychain off` once (or export `GCX_KEYCHAIN=off`). The token then lives in `~/.config/gcx/config.yaml` at mode 600. Note that `gcx alert` manages Grafana-managed alert rules and does not see the Prometheus rules in `deploy/prometheus/alerts.yml` — those remain the alerting source of truth.

6.7 forge_audit (Python package, not a script)
`AuditLog(path)` appends one JSON line per guardrail decision and chains each record to its predecessor's hash.

```python
from forge_audit import AuditLog

log = AuditLog("audit.jsonl")
log.record(
    input_text=prompt,
    policy="guardrail.input.v1",
    action="block",
    reason="prompt_injection",
    request_id=req_id,
    tenant_id=tenant,
)
log.verify()  # raises ValueError if a record was edited, reordered or removed
log.to_csv("export.csv")
log.to_json("export.json")
```

`input_text` is hashed with SHA-256 and never stored. Records carry `timestamp, input_hash, policy, action, reason, request_id, tenant_id, prev, hash` — the first five are A3's contracted fields, the rest are correlation and chain state.

The guarantee is **tamper-evident, not tamper-proof**: `verify()` detects modification, but anyone with the file can rewrite the whole chain. Real immutability needs WORM storage or shipping each batch to an append-only sink, which is infrastructure this repo does not have. Say so before claiming immutability to an auditor.

6.8 new-issue.sh
```
./scripts/new-issue.sh --title T --body-file F --dimension D --phase P \
                       --priority P --standard S --milestone M --epic "Epic X" \
                       [--labels a,b] [--dry-run]
```
Creates the issue, waits for the project's auto-add workflow (falling back to `item-add`), sets Dimension/Phase/Priority/Standard, sets the repository milestone, attaches the issue to its epic as a sub-issue, then runs `validate-project.sh`.

Rejects any value outside the MATRIX.md §8 vocabulary instead of writing drift. `--dry-run` prints the resolved values and exits without writing.

Exit codes: 0 on success including a clean validation, 1 on bad input, an unknown epic, or a board that fails validation.

6.9 forge_guard (Python package, not a script)
Forge is a **stress-test harness**: it sends adversarial input to a target system on purpose, so the guard's job is to label and record that input, not to stop it. `Guard().check(text)` returns a `Decision` with an action (`allow`/`log`/`flag`/`block`), the findings, and the OWASP risks they map to.

**The default action is `log`, not `block`.** Detection categories map to observe by default; a payload that is blocked never reaches the target and the test does not happen. Enforcement is opt-in:

```python
Guard(policy={"prompt_injection": "block", "system_prompt_leak": "block"})
```

The harness path looks like this — no `blocked` check, because the payload must reach the target:

```python
guard = Guard(audit=AuditLog("audit.jsonl"), review_queue="review.jsonl")
decision = guard.check(prompt, request_id=req_id, tenant_id=tenant)  # action == "log"
send_to_target(prompt)
```

Rules are **phrase-level**, not word-level, and derive from the OWASP *LLM Prompt Injection Prevention* cheat sheet's attack catalogue. `"how do I delete my account?"` and `"what are the system requirements?"` must stay allowed; both are covered by tests.

Normalisation produces a **screened copy**, never the text that gets forwarded: NFKC, zero-width and Unicode-tag stripping, and Base64/hex candidates decoded for inspection only. Anything normalisation changed is reported as a finding (`invisible_characters`, `encoded_payload`, `input_truncated`) rather than silently fixed.

`ModelDetector(classify)` wraps a classifier the deployment supplies — it returns `(category, score)` and the detector applies `block_at`/`flag_at` thresholds. No model is bundled: naming one here would be a dependency nobody asked for, and the agent already talks to an OpenAI-compatible endpoint.

Flagged decisions are appended to the review queue and every non-`allow` decision goes to the audit log (A3), so an observed payload still becomes evidence even though it was forwarded.

Wiring a real classifier:

```python
from forge_guard import Guard, ModelDetector
from forge_guard.openrouter import classifier

guard = Guard(detectors=[ModelDetector(classifier(model="openai/gpt-4o-mini"), block_at=0.8)])
```

`classifier()` resolves `model`, base URL and key from arguments then `OPENROUTER_MODEL` / `OPENROUTER_BASE_URL` / `OPENROUTER_API_KEY`. It asks the model for JSON `{"category", "score"}` and tolerates a fenced code block around it.

**Failure policy: a classifier that cannot answer produces a `classifier_error` finding with action `flag`** — never a silent `allow`, never a `block`. A classifier outage must not pass traffic unexamined, and must not take the API down either. Retries and circuit breaking are E1.

**This is not a security boundary.** Per the cheat sheet, an LLM does not separate instructions from data and a deny list can be rephrased around. Known gaps: paraphrases, other languages, typoglycemia (`ignroe`), and Best-of-N retries. Rate limiting is E2 and tool-call authorization is D4; neither is replaced by this package. Treat a block as a signal for logging and review, not as proof the input was safe.

6.10 forge_harness (Python package, not a script)
Sends each case to a target, labels the input with `forge_guard`, labels the response with the output rules, and writes both halves to the audit log.

```python
from forge_harness import Runner, Target, load_corpus

cases = load_corpus("harness/corpus/injection.json")
run = Runner(audit=AuditLog("audit.jsonl")).run(cases, Target("http://localhost:8000", token=TOKEN))
print(run.summary())  # cases, by_expectation, labelled_leaks, errors
run.to_json("run.json")
```

`Case(id, prompt, expectation, tags, canary)` — `canary` is a string the payload tells the target to emit, so "it refused" becomes provable rather than a judgement call. The corpus accepts a JSON array or JSONL.

`Target(base_url, path="/v1/chat/completions", model=..., token=...)` posts an OpenAI-compatible body. `token` accepts a string or a callable, resolved per request, so an expiring grant refreshes itself:

```python
from forge_harness.auth import KeycloakPasswordGrant

target = Target("http://localhost:8000", token=KeycloakPasswordGrant())
```

`KeycloakPasswordGrant` reads `BASTION_TOKEN_URL`, `BASTION_CLIENT_ID`, `BASTION_USERNAME` (or `BASTION_USER`) and `BASTION_PASSWORD`, caches the access token, and refreshes `refresh_margin` seconds before `expires_in` runs out. It raises `TokenError` with Keycloak's own `error_description` rather than a bare HTTP status. A target that 500s, or that is not listening at all, is recorded (`status` 500 or 0) rather than raising: a dead target is a result.

Omit `model=` and the target is asked once via `GET /v1/models`, because a gateway rejects models it does not serve — bastion-agent answers `404 model 'gpt-4o-mini' is not served by this gateway` for anything but its own ids.

Every record carries a `verdict`, decided in this order: `error` (status ≥ 400 or transport failure) → `injected` (the canary appears in the response) → `leaked` (the response trips LLM07) → `blocked` (the gateway says so: `finish_reason: content_filter` or an extension such as `bastion.blocked`) → `refused` (empty body or a refusal phrase) → `answered` (a benign case that got a real answer) → `unclear`. The canary outranks prose reading: a target that says "I can't help with that, but OWNED" has still been injected. A gateway's own block signal outranks heuristics — read `finish_reason` and any extension object before guessing from an empty body.

Pass a tracer to get one span per case, which the collector forwards to Langfuse:

```python
from forge_harness import init_tracing

run = Runner(tracer=init_tracing()).run(cases, target)
```

Spans are named `harness.case <id>` and carry `harness.verdict`, the input/response labels and the HTTP status. An `injected` verdict sets span status ERROR, so a canary echo is visible in the trace list rather than only in the report. `FORGE_OTEL_ENDPOINT` must point at the collector (`http://localhost:14318`); without it, spans are created and dropped.

`Run.summary()` counts `by_verdict` and exposes `injections_succeeded`. `Record.response_excerpt` keeps the first 500 characters so a result can be looked at; the audit log still stores hashes only.

Output labelling uses `forge_guard.OUTPUT_RULES` — leak-shaped patterns — not the request-shaped input rules. Asking for a system prompt and *receiving* one are different signals; mixing them labels every extraction attempt as a leak in the response.

Nothing here blocks. That is the whole point of Forge: the payload must reach the target.

7. Known API gotchas
Each of these has already cost time in this repository. Do not re-discover them.

Symptom	Cause	Fix
Cannot index array with string "items"	Script written against old gh project item-list shape {items:…}; fetch-items.sh returns a bare array.	Use .[], not .items[]. If sed-ing, exclude fetch-items.sh.
--field cannot be used with --id	CLI rejects mixed addressing modes.	Use --field-id + --project-id + --id, and a type-specific value flag (--single-select-option-id or --text).
Issue field values cannot be updated using updateProjectV2ItemFieldValue	The field is an issue field (Milestone, Labels, Assignees), not a custom project field.	Set them on the issue: gh issue edit --milestone / --add-label / --add-assignee.
--format json rejected together with --field	Mutually exclusive on gh project item-list.	Use fetch-items.sh (GraphQL).
@me unusable in GraphQL	It is a CLI alias, not a login.	OWNER=$(gh api user --jq .login) before any GraphQL call.
Could not resolve to a ProjectV2	Trying node(id: owner) { ... on User { projectV2(…) } }.	Query user(login: …) { projectV2(number: …) } directly.
Options truncated at first comma	--single-select-options splits on ,.	Keep option labels comma-free.
ascii_downcase cannot be applied to: null	A field value of a type missing from fetch-items.sh's fragments (a date value) has no .field.	Keep the select(.field?.name != null) guard when adding field types.
Content already exists in this project	A built-in project workflow auto-adds new issues, so item-add can lose the race.	Look the item up instead of adding it; retry for a few seconds after gh issue create.
Failed to add sub-issue … duplicate	An issue can have exactly one parent and cannot be added twice.	Ignore the error on re-run; verify via fetch-items .epic instead.
gh project item-delete rejects --project-id	It takes --owner, not --project-id.	gh project item-delete <num> --owner @me --id PVTI_…
http.status_code appears instead of http.response.status_code	The FastAPI instrumentor defaults to pre-1.20 semantic conventions.	forge_otel sets http.response.status_code in its own send wrapper.
Duplicate exception span events	start_as_current_span records exceptions and sets status by default.	Pass record_exception=False, set_status_on_exception=False when recording manually.
Middleware sees no active span	Starlette wraps in reverse add order, so the last-added middleware is outermost.	Add attribute middleware before FastAPIInstrumentor.instrument_app.
TestClient re-raises the endpoint's exception	raise_server_exceptions=True is the default.	TestClient(app, raise_server_exceptions=False) when asserting on a 5xx.

8. Canonical workflows for agents
8.1 Creating a story
Use the script rather than the manual sequence; it sets every field, waits out the auto-add race, attaches the epic and validates:

```
./scripts/new-issue.sh --title "A6. …" --body-file /tmp/body.md \
  --dimension Operational --phase Baseline --priority P2 \
  --standard "NIST AI RMF" --milestone "M1 Baseline" \
  --epic "Epic A" --labels story,observability
```

`--dry-run` prints the resolved values without writing. Add dependencies afterwards with `./block.sh "<story>" "<blocker>"`.

The same procedure is packaged as the `capture-issue` skill (`.agents/skills/capture-issue/SKILL.md`), so an agent reading only skill descriptions finds it.

8.2 Daily standup check
bash
./scripts/validate-project.sh
./scripts/fetch-items.sh | jq -r '
  .[] | select(.status == "Ready" and (.blockedby // "") == "")
      | [.priority, .title] | @tsv' | sort
The second command lists every workable item in Ready — that is the sprint candidate set.

8.3 Closing a blocker
Move the blocker to `Done` and close its issue. GitHub marks dependents unblocked on its own; nothing to sweep. If you want the relation gone, `gh issue edit <n> --remove-blocked-by <m>`.

9. Conventions for agents editing this repo
The project is the source of truth. Do not add a CSV, JSON or YAML mirror of stories, dimensions or standards — that is the duplication this repo deliberately removed. If something cannot be expressed in the project, change the project schema, not the filesystem.

Never add a custom field that duplicates a native feature. Before creating one, check: Labels, Milestone, Assignees, Parent issue and blocked-by relations all exist already.

Run ./scripts/validate-project.sh before committing anything that touches the board, and paste its output in the PR. A green validator is the only evidence the board is coherent.

Keep MATRIX.md §8 and validate-project.sh's STANDARDS list in sync. They are the same vocabulary in two places, and the validator is what makes the drift visible.

Never edit files inside .github/, scripts/, or this file without updating the corresponding section here. Agents that leave the documentation stale cause more damage than agents that leave code buggy.

Prefer ./fetch-items.sh over gh project item-list in any new script. The --field / --format conflict will bite the moment you need a custom field.

Never mix --field and --id. Pick one addressing mode per gh call.

Idempotency is a hard requirement. Every script must be safe to run twice in a row.

`main` is protected: the `quality-and-tests` job must pass and direct pushes are rejected, including for administrators. Work on a branch and open a pull request (`gh pr create --fill`). Force pushes and branch deletion are blocked, so rewriting history requires dropping the protection rule first. The repository is public, so fork pull requests skip the project-board step — secrets are not exposed to them.

10. When you get stuck
If a script fails, run it under bash -xv first. The last two lines of trace plus the failing gh or jq command almost always identify the issue by inspection.

If fetch-items.sh returns an empty array but the UI shows items:

gh auth status — confirm project scope.

Re-derive the project ID: gh project list --owner @me --format json.

Confirm the owner: an org-owned project cannot be resolved through user(login:).

If a jq filter returns zero rows but the field is visibly populated in the UI:

./scripts/fetch-items.sh | jq '.[0] | keys' — confirm the sanitized key name.

The sanitizer is ascii_downcase | gsub("[^a-z0-9]"; "") — a field with a punctuation character produces a key you did not anticipate.

If you are still stuck, open an issue titled agent: <script> — <symptom> and include the full bash -xv trace plus gh auth status output.
