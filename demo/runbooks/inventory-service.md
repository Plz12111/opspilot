# Inventory Service Recovery

## High error rate

Check `demo_http_requests_total` for 5xx responses and compare the first error with recent
deployments. Inspect traces from Order Service to Inventory Service for timeout or 503 spans.

## Database connection pool exhausted

If the active connection count reaches the configured maximum, inspect requests that fail to
release connections. A restart is only a temporary mitigation; prefer rolling back the leaking
deployment after approval.

## Verification

Confirm error rate remains below one percent and P95 latency remains below 500 ms for five
minutes before resolving the incident.

