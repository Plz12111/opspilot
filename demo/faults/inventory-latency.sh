#!/usr/bin/env sh
set -eu

BASE_URL="${INVENTORY_URL:-http://127.0.0.1:8082}"
TOKEN="${DEMO_FAULT_TOKEN:-demo-only}"

curl --fail --silent --show-error \
  -X PUT "${BASE_URL}/internal/faults" \
  -H "Content-Type: application/json" \
  -H "X-Fault-Token: ${TOKEN}" \
  -d '{"latency_ms":1000,"error_rate":0.0}'
