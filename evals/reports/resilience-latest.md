# OpsPilot resilience report

- Generated: `2026-07-22T07:19:57.397978+00:00`
- Run ID: `8ba20f69b308`
- Result: **PASS**
- Requests: **415**

| Scenario | Result | Requests | RPS | P50 | P95 | P99 | Statuses |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `duplicate_alert_burst` | PASS | 50 | 233.12 | 198.76 ms | 213.26 ms | 214.11 ms | 202=50 |
| `distinct_alert_merge` | PASS | 50 | 257.82 | 164.01 ms | 190.29 ms | 191.2 ms | 202=50 |
| `order_idempotency_burst` | PASS | 200 | 721.59 | 63.38 ms | 94.86 ms | 117.33 ms | 200=200 |
| `investigation_idempotency_burst` | PASS | 20 | 117.99 | 164.42 ms | 169.11 ms | 169.14 ms | 202=20 |
| `remediation_exactly_once_burst` | PASS | 60 | 278.98 | 26.97 ms | 148.77 ms | 151.74 ms | 200=40, 201=20 |
| `dependency_failure_and_recovery` | PASS | 35 | 614.07 | 32.32 ms | 45.65 ms | 45.93 ms | 200=5, 503=30 |

## Business invariants

### `duplicate_alert_burst`

- PASS — `all_requests_accepted`
- PASS — `one_incident_created`
- PASS — `all_retries_deduplicated`

### `distinct_alert_merge`

- PASS — `all_requests_accepted`
- PASS — `occurrences_merged_to_one_incident`
- PASS — `alert_count_is_atomic`

### `order_idempotency_burst`

- PASS — `all_orders_succeeded`
- PASS — `order_ids_are_idempotent`
- PASS — `inventory_reserved_once_per_order`

### `investigation_idempotency_burst`

- PASS — `all_requests_accepted`
- PASS — `one_run_created`
- PASS — `run_reached_terminal_state`

### `remediation_exactly_once_burst`

- PASS — `one_action_proposed`
- PASS — `approval_is_idempotent`
- PASS — `execution_is_exactly_once`

### `dependency_failure_and_recovery`

- PASS — `fault_control_accepted`
- PASS — `dependency_errors_propagated_as_503`
- PASS — `fault_was_reset`
- PASS — `service_recovered`

