#!/usr/bin/env bash
# Bring up the observability stack.
#
#   ./up.sh            # compose up -d
#   ./up.sh logs -f    # any other compose subcommand
#
# Reads Langfuse's native variables and derives the two the collector needs:
#   LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY -> LANGFUSE_AUTH_STRING (base64)
#   LANGFUSE_BASE_URL                         -> LANGFUSE_OTLP_ENDPOINT
set -euo pipefail
cd "$(dirname "$0")"

ENV_FILE="${ENV_FILE:-../.env}"
[[ -f "$ENV_FILE" ]] || ENV_FILE=".env"
[[ -f "$ENV_FILE" ]] || {
  echo "no .env found in deploy/ or the repo root; copy deploy/.env.example" >&2
  exit 1
}

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

: "${LANGFUSE_PUBLIC_KEY:?LANGFUSE_PUBLIC_KEY is not set in $ENV_FILE}"
: "${LANGFUSE_SECRET_KEY:?LANGFUSE_SECRET_KEY is not set in $ENV_FILE}"
: "${LANGFUSE_BASE_URL:?LANGFUSE_BASE_URL is not set in $ENV_FILE}"

export LANGFUSE_OTLP_ENDPOINT="${LANGFUSE_BASE_URL%/}/api/public/otel"
export LANGFUSE_AUTH_STRING="$(printf '%s:%s' "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)"

if [[ $# -eq 0 ]]; then
  exec docker compose up -d
fi
exec docker compose "$@"
