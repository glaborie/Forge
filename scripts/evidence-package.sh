#!/usr/bin/env bash
# Build an evidence index for the frameworks an operator selected.
#
#   ./scripts/fetch-items.sh 5 | ./scripts/evidence-package.sh "Swiss FADP,FINMA"
#   FORGE_FRAMEWORKS="Swiss FADP" ./scripts/fetch-items.sh 5 | ./scripts/evidence-package.sh
#
# Applicability is the operator's decision: this script never infers a framework
# from the target, and it refuses a name that is not in the MATRIX §8 vocabulary.
# The work lives in `forge_compliance`, so a dashboard can call the same function.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SELECTION="${1:-${FORGE_FRAMEWORKS:-}}"

PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" \
    exec python3 -m forge_compliance --matrix "$ROOT/MATRIX.md" --frameworks "$SELECTION"
