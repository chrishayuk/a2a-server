#!/usr/bin/env bash
# debug_scripts/debug_smoke_test.sh.sh - smoke-test for a2a-server with Prometheus metrics
set -euo pipefail

CFG=${1:-agent.yaml}
PORT=${PORT:-8000}
HOST=${HOST:-127.0.0.1}
METRICS_PATH=${METRICS_PATH:-/metrics}

cyan() { printf '\033[1;36m%s\033[0m\n' "$*"; }
log()  { cyan "[$(date +%T)] $*"; }

# ── 1 · ensure port free ────────────────────────────────────────────────
if lsof -Pi :"$PORT" -sTCP:LISTEN -t &>/dev/null; then
  log "Port $PORT busy - killing existing Uvicorn process"
  pkill -f "uvicorn.*a2a_server" || true
  sleep 1
fi

# ── 2 · env - pull mode only ────────────────────────────────────────────
export PROMETHEUS_METRICS=true
unset OTEL_EXPORTER_OTLP_ENDPOINT

# ── 3 · launch server ───────────────────────────────────────────────────
log "Starting a2a-server on :$PORT …"
uv run a2a-server --config "$CFG" --log-level info &>server.log &
PID=$!
trap 'log "Stopping server"; kill $PID 2>/dev/null || true' EXIT INT TERM

# wait for OpenAPI to come up
for _ in {1..30}; do
  curl -sf "http://$HOST:$PORT/docs" >/dev/null && break
  sleep 0.3
done || { log "❌ server failed to start (see server.log)"; exit 1; }
log "Server is up ✅"

# ── 4 · fire an RPC call ────────────────────────────────────────────────
REQ='{"jsonrpc":"2.0","id":"1","method":"tasks/send","params":{"id":"ignored","message":{"role":"user","parts":[{"type":"text","text":"Ahoy!"}]}}}'
log "Sending tasks/send RPC"
RESP=$(curl -s -H 'Content-Type: application/json' --data "$REQ" "http://$HOST:$PORT/rpc")
[[ -z "$RESP" ]] && { log "❌ empty RPC response"; exit 1; }

if command -v jq &>/dev/null; then
  echo "$RESP" | jq .
else
  echo "$RESP"
fi

# ── 5 · wait until /metrics exists (Prometheus reader starts async) ────
for _ in {1..30}; do
  HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://$HOST:$PORT$METRICS_PATH") || true
  [[ "$HTTP_CODE" == "200" ]] && break
  sleep 0.3
done || { log "❌ /metrics never became available"; exit 1; }

log "Fetching $METRICS_PATH (first 15 lines)"
curl -s "http://$HOST:$PORT$METRICS_PATH" | head -n 15

log "✅ Done - full server log saved to server.log"
