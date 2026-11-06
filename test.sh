#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
(cd backend && . .venv/bin/activate && python -m pytest -q)
(cd frontend && npm run typecheck)
