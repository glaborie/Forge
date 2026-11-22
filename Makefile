# Operator entry points. The UI dashboard will call the same module, not these recipes.
FORGE_PROJECT ?= 5
FRAMEWORKS ?=
PACKAGE ?= evidence-package.md

TARGET ?= http://localhost:8000
CORPUS ?= harness/corpus/injection.json
ROLES ?= admin
ARGS ?=

EVAL_DATASET ?= evaluation/golden.json
EVAL_RUN ?= evaluation/run.json
EVAL_THRESHOLDS ?= evaluation/thresholds.json
EVAL_REPORT ?= evaluation-report.json
JUDGE_MODEL ?=

.PHONY: validate fetch package test live eval gate

validate:  ## board drift gate
	./scripts/validate-project.sh $(FORGE_PROJECT)

fetch:  ## flat JSON snapshot of the project on stdout
	./scripts/fetch-items.sh $(FORGE_PROJECT)

package:  ## evidence index for the selected frameworks: make package FRAMEWORKS="Swiss FADP"
	./scripts/fetch-items.sh $(FORGE_PROJECT) | ./scripts/evidence-package.sh "$(FRAMEWORKS)" > $(PACKAGE)
	@echo "wrote $(PACKAGE)"

live:  ## live run: make live ROLES=all ARGS="--tracing --spec http://localhost:8000/openapi.json"
	@if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	uv run python -m forge_harness --target $(TARGET) --corpus $(CORPUS) --roles "$(ROLES)" $(ARGS)

eval:  ## record a live evaluation run: make eval JUDGE_MODEL=openai/gpt-4o-mini
	@if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	uv run python -m forge_eval run --dataset $(EVAL_DATASET) --target $(TARGET) \
	  --thresholds $(EVAL_THRESHOLDS) --out $(EVAL_RUN) \
	  $(if $(JUDGE_MODEL),--judge-model $(JUDGE_MODEL)) $(ARGS)

gate:  ## offline threshold check, the same command CI runs
	uv run python -m forge_eval check --run $(EVAL_RUN) --dataset $(EVAL_DATASET) \
	  --thresholds $(EVAL_THRESHOLDS) --report $(EVAL_REPORT)

test:  ## ruff, mypy, pytest
	uv run ruff check .
	uv run ruff format --check .
	uv run python -m mypy src/
	uv run pytest -q
