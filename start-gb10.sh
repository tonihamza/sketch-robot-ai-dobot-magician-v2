#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export DOBOT_AI_BACKEND=local
exec .venv/bin/python start.py
