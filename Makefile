# Operator entry points. The UI dashboard will call the same module, not these recipes.
FORGE_PROJECT ?= 5
FRAMEWORKS ?=
PACKAGE ?= evidence-package.md

TARGET ?= http://localhost:8000
CORPUS ?= harness/corpus/injection.json
ROLES ?= admin
ARGS ?=

.PHONY: validate fetch package test live

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

test:  ## ruff, mypy, pytest
	uv run ruff check .
	uv run ruff format --check .
	uv run python -m mypy src/
	uv run pytest -q
