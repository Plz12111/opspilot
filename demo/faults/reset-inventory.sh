#!/usr/bin/env sh
set -eu

BASE_URL="${INVENTORY_URL:-http://127.0.0.1:8082}"
TOKEN="${DEMO_FAULT_TOKEN:-demo-only}"

curl --fail --silent --show-error \
  -X DELETE "${BASE_URL}/internal/faults" \
  -H "X-Fault-Token: ${TOKEN}"
