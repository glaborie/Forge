---
name: capture-issue
description: Capture a new story on the Forge board (GitHub Project #5) with every field set, attached to its epic, and validated. Use when the user asks to file, capture, record or backlog a new issue, story, follow-up, defect or idea for glaborie/Forge.
---

# Capture an issue on the Forge board

The board is the source of truth: an issue is not "captured" until it is an issue in `glaborie/Forge`, in project #5, with its fields set, attached to an epic, and passing the validator. Creating the issue alone is half the job and leaves drift the validator will reject.

## One command

```bash
./scripts/new-issue.sh \
  --title "A6. <imperative sentence>" \
  --body-file /tmp/body.md \
  --dimension Operational --phase Baseline --priority P2 \
  --standard "NIST AI RMF" --milestone "M1 Baseline" \
  --epic "Epic A" --labels story,observability
```

Dry run first when the vocabulary is new to you: add `--dry-run`.

## Inputs you must decide before running

| Flag | Allowed values |
| --- | --- |
| `--dimension` | Functional, Security, Operational, Temporal, Cross-cutting |
| `--phase` | Baseline, Guardrails, Evaluation, Red Teaming, Continuous Improvement |
| `--priority` | P0, P1, P2, P3 |
| `--standard` | MATRIX.md §8 identifiers, `; `-separated (e.g. `"CSA AICM; EU AI Act"`), or `N/A` |
| `--milestone` | M1 Baseline, M2 Guardrails, M3 Evaluation, M4 Red Teaming, M5 Continuous Improvement |
| `--epic` | title prefix: `Epic A`, `Epic B`, … `Epic G` |
| `--labels` | existing repo labels: story, compliance, security, observability, evaluation, guardrails, red-team, drift |

The script rejects any value outside those sets rather than writing drift into the board. If a genuine new value is needed, change `MATRIX.md` §8 and `scripts/validate-project.sh` together first.

## Body shape

Follow the existing stories: one "As a …, I want …, so that …" sentence, then `AC:` with bullets that are individually checkable, then `Non-goals:` when the boundary is not obvious. Multi-line bodies go in a file — never inline in the shell.

## What the script does

1. Creates the issue with labels.
2. Waits for the project's auto-add workflow, falling back to an explicit `item-add` if it loses the race.
3. Sets Dimension, Phase, Priority and Standard on the project item.
4. Sets the repository milestone.
5. Adds the issue as a sub-issue of its epic.
6. Runs `scripts/validate-project.sh`, which fails loudly on any inconsistency.

## Verify

The last line should be `OK: N items, M epics, no drift` and the issue number. If the validator complains, fix the board — do not relax the validator.

## Traps

- A story can have exactly one parent epic; re-parenting means removing the old link first.
- PRs are auto-added to the board too. The validator ignores them; do not "fix" a PR card by giving it a Dimension.
- `--standard` is a controlled vocabulary, not free text. `OWASP LLM01` is a control ID and is rejected; use `OWASP LLM Top 10` and put the control ID in the body.
- The board is the only record. Do not also append to a spreadsheet, CSV or JSON — those were deliberately deleted from this repo.
