#!/usr/bin/env bash
# Desenvolvimento: API com reload (8000) + Vite com HMR (5173)
set -euo pipefail
cd "$(dirname "$0")/.."
. .venv/bin/activate
(cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) &
trap "kill 0" EXIT
cd frontend && npm run dev
