# Order Service Recovery

## Downstream inventory timeout

Check Inventory Service health, 503 responses, and slow Trace spans. Preserve the original
order ID for every retry so inventory reservation remains idempotent.

## Recovery

Restore Inventory Service before increasing Order Service traffic. Do not retry requests without
an idempotency key.

## Verification

Confirm successful inventory reservations and observe the Order Service error rate for five
minutes.

