#!/usr/bin/env sh
set -eu

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
DURATION_SECONDS="${DURATION_SECONDS:-25}"

cleanup() {
  sh "$(dirname "$0")/../faults/reset-inventory.sh" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

sh "$(dirname "$0")/../faults/inventory-error.sh"

end_at=$(( $(date +%s) + DURATION_SECONDS ))
sequence=0
while [ "$(date +%s)" -lt "$end_at" ]; do
  sequence=$((sequence + 1))
  curl --silent --output /dev/null \
    -X POST "${GATEWAY_URL}/api/v1/orders" \
    -H "Content-Type: application/json" \
    -d "{\"order_id\":\"error-${sequence}\",\"sku\":\"SKU-001\",\"quantity\":1}" || true
  sleep 0.5
done
