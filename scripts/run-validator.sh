#!/usr/bin/env bash
# Interpreter discovery for the convention validator — hooks run in a bare
# environment, so we resolve python3/uv ourselves instead of trusting PATH.
# Usage: scripts/run-validator.sh <args forwarded to check_conventions.py>
set -euo pipefail

PATH="$HOME/.local/bin:$PATH"
cd "$(git rev-parse --show-toplevel)"

if command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/check_conventions.py "$@"
fi
if command -v uv >/dev/null 2>&1; then
  exec uv run --no-project scripts/check_conventions.py "$@"
fi

echo "conventions: no python3 or uv on PATH — cannot check (fix setup or --no-verify; CI still enforces)" >&2
exit 1
