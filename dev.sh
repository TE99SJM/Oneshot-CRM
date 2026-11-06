#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
(cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT
cd frontend && npm run dev
