#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -r requirements-dev.txt
cd ../frontend && npm install
echo "Setup complete. ./dev.sh for development, ./start.sh for a single-server run."
