#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON="${PYTHON:-python3}"

cd "$SCRIPT_DIR"
exec "$PYTHON" trading_assistant.py --config config.json "$@"
