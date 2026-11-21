# Operator entry points. The UI dashboard will call the same module, not these recipes.
FORGE_PROJECT ?= 5
FRAMEWORKS ?=
PACKAGE ?= evidence-package.md

.PHONY: validate fetch package test

validate:  ## board drift gate
	./scripts/validate-project.sh $(FORGE_PROJECT)

fetch:  ## flat JSON snapshot of the project on stdout
	./scripts/fetch-items.sh $(FORGE_PROJECT)

package:  ## evidence index for the selected frameworks: make package FRAMEWORKS="Swiss FADP"
	./scripts/fetch-items.sh $(FORGE_PROJECT) | ./scripts/evidence-package.sh "$(FRAMEWORKS)" > $(PACKAGE)
	@echo "wrote $(PACKAGE)"

test:  ## ruff, mypy, pytest
	uv run ruff check .
	uv run ruff format --check .
	uv run python -m mypy src/
	uv run pytest -q
