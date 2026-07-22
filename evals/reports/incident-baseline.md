# OpsPilot Incident Agent Baseline

- Suite: `incident-agent-baseline-v1`
- Baseline: `source-weighted-v2`
- Cases: `80`
- Dataset SHA-256: `fe8a7989e8ad700609984b9d7718bd41a378a3f82ece32565d8d326109210fda`
- Result: `PASS`

## Aggregate metrics

| Metric | Actual | Threshold | Result |
| --- | ---: | ---: | --- |
| Top-1 accuracy | 93.8% | >= 60.0% | PASS |
| Top-3 recall | 97.5% | >= 80.0% | PASS |
| Citation validity | 100.0% | >= 90.0% | PASS |
| Tool success rate | 98.5% | >= 95.0% | PASS |
| Prohibited action rate | 0.0% | <= 0.0% | PASS |
| Critical evidence recall | 100.0% | report only | - |
| Average steps | 5.00 | report only | - |
| P95 latency | 7 ms | report only | - |

## Case results

| Case | Expected | Top prediction | Top-1 | Top-3 | Evidence |
| --- | --- | --- | --- | --- | ---: |
| `inventory-503-clear` | `inventory_dependency_failure` | `inventory_dependency_failure` | PASS | PASS | 100% |
| `inventory-refused-trace` | `inventory_dependency_failure` | `inventory_dependency_failure` | PASS | PASS | 100% |
| `inventory-503-with-latency-noise` | `inventory_dependency_failure` | `inventory_latency` | FAIL | PASS | 100% |
| `inventory-latency-clear` | `inventory_latency` | `inventory_latency` | PASS | PASS | 100% |
| `inventory-deadline-trace` | `inventory_latency` | `inventory_latency` | PASS | PASS | 100% |
| `inventory-latency-telemetry-gap` | `inventory_latency` | `undetermined` | FAIL | FAIL | 100% |
| `database-pool-clear` | `database_pool_exhaustion` | `database_pool_exhaustion` | PASS | PASS | 100% |
| `database-pool-after-deploy-noise` | `database_pool_exhaustion` | `database_pool_exhaustion` | PASS | PASS | 100% |
| `database-pool-metrics` | `database_pool_exhaustion` | `database_pool_exhaustion` | PASS | PASS | 100% |
| `redis-stampede-clear` | `redis_cache_stampede` | `redis_cache_stampede` | PASS | PASS | 100% |
| `redis-eviction-runbook` | `redis_cache_stampede` | `redis_cache_stampede` | PASS | PASS | 100% |
| `redis-stampede-telemetry-gap` | `redis_cache_stampede` | `undetermined` | FAIL | FAIL | 100% |
| `deployment-regression-clear` | `bad_deployment` | `bad_deployment` | PASS | PASS | 100% |
| `deployment-trace-regression` | `bad_deployment` | `bad_deployment` | PASS | PASS | 100% |
| `deployment-with-memory-noise` | `bad_deployment` | `memory_leak` | FAIL | PASS | 100% |
| `memory-leak-clear` | `memory_leak` | `memory_leak` | PASS | PASS | 100% |
| `memory-oom-restart` | `memory_leak` | `memory_leak` | PASS | PASS | 100% |
| `memory-with-disk-noise` | `memory_leak` | `disk_saturation` | FAIL | PASS | 100% |
| `network-partition-clear` | `network_partition` | `network_partition` | PASS | PASS | 100% |
| `network-reset-traces` | `network_partition` | `network_partition` | PASS | PASS | 100% |
| `network-with-tls-noise` | `network_partition` | `network_partition` | PASS | PASS | 100% |
| `certificate-expired-clear` | `certificate_expiry` | `certificate_expiry` | PASS | PASS | 100% |
| `certificate-handshake-trace` | `certificate_expiry` | `certificate_expiry` | PASS | PASS | 100% |
| `certificate-with-log-outage` | `certificate_expiry` | `certificate_expiry` | PASS | PASS | 100% |
| `rate-limit-clear` | `rate_limit_exhaustion` | `rate_limit_exhaustion` | PASS | PASS | 100% |
| `rate-limit-metrics` | `rate_limit_exhaustion` | `rate_limit_exhaustion` | PASS | PASS | 100% |
| `rate-limit-with-network-noise` | `rate_limit_exhaustion` | `rate_limit_exhaustion` | PASS | PASS | 100% |
| `disk-saturation-clear` | `disk_saturation` | `disk_saturation` | PASS | PASS | 100% |
| `disk-no-space-logs` | `disk_saturation` | `disk_saturation` | PASS | PASS | 100% |
| `disk-with-memory-noise` | `disk_saturation` | `disk_saturation` | PASS | PASS | 100% |
| `inventory-dependency-failure-corroborated` | `inventory_dependency_failure` | `inventory_dependency_failure` | PASS | PASS | 100% |
| `inventory-dependency-failure-single-log` | `inventory_dependency_failure` | `inventory_dependency_failure` | PASS | PASS | 100% |
| `inventory-dependency-failure-runbook-noise` | `inventory_dependency_failure` | `inventory_dependency_failure` | PASS | PASS | 100% |
| `inventory-dependency-failure-telemetry-gap` | `inventory_dependency_failure` | `inventory_dependency_failure` | PASS | PASS | 100% |
| `inventory-dependency-failure-ambiguous-noise` | `inventory_dependency_failure` | `inventory_dependency_failure` | PASS | PASS | 100% |
| `inventory-latency-corroborated` | `inventory_latency` | `inventory_latency` | PASS | PASS | 100% |
| `inventory-latency-single-log` | `inventory_latency` | `inventory_latency` | PASS | PASS | 100% |
| `inventory-latency-runbook-noise` | `inventory_latency` | `inventory_latency` | PASS | PASS | 100% |
| `inventory-latency-telemetry-gap` | `inventory_latency` | `inventory_latency` | PASS | PASS | 100% |
| `inventory-latency-ambiguous-noise` | `inventory_latency` | `inventory_latency` | PASS | PASS | 100% |
| `database-pool-exhaustion-corroborated` | `database_pool_exhaustion` | `database_pool_exhaustion` | PASS | PASS | 100% |
| `database-pool-exhaustion-single-log` | `database_pool_exhaustion` | `database_pool_exhaustion` | PASS | PASS | 100% |
| `database-pool-exhaustion-runbook-noise` | `database_pool_exhaustion` | `database_pool_exhaustion` | PASS | PASS | 100% |
| `database-pool-exhaustion-telemetry-gap` | `database_pool_exhaustion` | `database_pool_exhaustion` | PASS | PASS | 100% |
| `database-pool-exhaustion-ambiguous-noise` | `database_pool_exhaustion` | `database_pool_exhaustion` | PASS | PASS | 100% |
| `redis-cache-stampede-corroborated` | `redis_cache_stampede` | `redis_cache_stampede` | PASS | PASS | 100% |
| `redis-cache-stampede-single-log` | `redis_cache_stampede` | `redis_cache_stampede` | PASS | PASS | 100% |
| `redis-cache-stampede-runbook-noise` | `redis_cache_stampede` | `redis_cache_stampede` | PASS | PASS | 100% |
| `redis-cache-stampede-telemetry-gap` | `redis_cache_stampede` | `redis_cache_stampede` | PASS | PASS | 100% |
| `redis-cache-stampede-ambiguous-noise` | `redis_cache_stampede` | `redis_cache_stampede` | PASS | PASS | 100% |
| `bad-deployment-corroborated` | `bad_deployment` | `bad_deployment` | PASS | PASS | 100% |
| `bad-deployment-single-log` | `bad_deployment` | `bad_deployment` | PASS | PASS | 100% |
| `bad-deployment-runbook-noise` | `bad_deployment` | `bad_deployment` | PASS | PASS | 100% |
| `bad-deployment-telemetry-gap` | `bad_deployment` | `bad_deployment` | PASS | PASS | 100% |
| `bad-deployment-ambiguous-noise` | `bad_deployment` | `bad_deployment` | PASS | PASS | 100% |
| `memory-leak-corroborated` | `memory_leak` | `memory_leak` | PASS | PASS | 100% |
| `memory-leak-single-log` | `memory_leak` | `memory_leak` | PASS | PASS | 100% |
| `memory-leak-runbook-noise` | `memory_leak` | `memory_leak` | PASS | PASS | 100% |
| `memory-leak-telemetry-gap` | `memory_leak` | `memory_leak` | PASS | PASS | 100% |
| `memory-leak-ambiguous-noise` | `memory_leak` | `memory_leak` | PASS | PASS | 100% |
| `network-partition-corroborated` | `network_partition` | `network_partition` | PASS | PASS | 100% |
| `network-partition-single-log` | `network_partition` | `network_partition` | PASS | PASS | 100% |
| `network-partition-runbook-noise` | `network_partition` | `network_partition` | PASS | PASS | 100% |
| `network-partition-telemetry-gap` | `network_partition` | `network_partition` | PASS | PASS | 100% |
| `network-partition-ambiguous-noise` | `network_partition` | `network_partition` | PASS | PASS | 100% |
| `certificate-expiry-corroborated` | `certificate_expiry` | `certificate_expiry` | PASS | PASS | 100% |
| `certificate-expiry-single-log` | `certificate_expiry` | `certificate_expiry` | PASS | PASS | 100% |
| `certificate-expiry-runbook-noise` | `certificate_expiry` | `certificate_expiry` | PASS | PASS | 100% |
| `certificate-expiry-telemetry-gap` | `certificate_expiry` | `certificate_expiry` | PASS | PASS | 100% |
| `certificate-expiry-ambiguous-noise` | `certificate_expiry` | `certificate_expiry` | PASS | PASS | 100% |
| `rate-limit-exhaustion-corroborated` | `rate_limit_exhaustion` | `rate_limit_exhaustion` | PASS | PASS | 100% |
| `rate-limit-exhaustion-single-log` | `rate_limit_exhaustion` | `rate_limit_exhaustion` | PASS | PASS | 100% |
| `rate-limit-exhaustion-runbook-noise` | `rate_limit_exhaustion` | `rate_limit_exhaustion` | PASS | PASS | 100% |
| `rate-limit-exhaustion-telemetry-gap` | `rate_limit_exhaustion` | `rate_limit_exhaustion` | PASS | PASS | 100% |
| `rate-limit-exhaustion-ambiguous-noise` | `rate_limit_exhaustion` | `rate_limit_exhaustion` | PASS | PASS | 100% |
| `disk-saturation-corroborated` | `disk_saturation` | `disk_saturation` | PASS | PASS | 100% |
| `disk-saturation-single-log` | `disk_saturation` | `disk_saturation` | PASS | PASS | 100% |
| `disk-saturation-runbook-noise` | `disk_saturation` | `disk_saturation` | PASS | PASS | 100% |
| `disk-saturation-telemetry-gap` | `disk_saturation` | `disk_saturation` | PASS | PASS | 100% |
| `disk-saturation-ambiguous-noise` | `disk_saturation` | `disk_saturation` | PASS | PASS | 100% |

## Interpretation

This is a deterministic keyword baseline, not a claim of model intelligence. Recorded noisy and missing-telemetry cases are kept in the aggregate rather than removed. Future prompt, model, and retrieval changes must compare against this same dataset digest.
