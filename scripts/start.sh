#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f runtime/orders.db ]; then uv run python scripts/manage.py generate; fi
uv run uvicorn order_agent.api:app --host 127.0.0.1 --port 8000 &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM
uv run streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
