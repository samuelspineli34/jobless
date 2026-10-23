#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
playwright install chromium
[ -f .env ] || cp .env.example .env
(cd frontend && npm install && npm run build)
echo; echo "Pronto! Rode: ./scripts/run.sh  e abra http://127.0.0.1:8000"
