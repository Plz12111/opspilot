# OpsPilot Baseline Comparison

- Dataset SHA-256: `fe8a7989e8ad700609984b9d7718bd41a378a3f82ece32565d8d326109210fda`
- Cases: `80`
- Repetitions: `3`

## Baseline vs candidate

| Metric | Keyword v1 | Source-weighted v2 | Delta |
| --- | ---: | ---: | ---: |
| Top-1 accuracy | 67.5% | 93.8% | +26.2% |
| Top-3 recall | 97.5% | 97.5% | +0.0% |
| Citation validity | 100.0% | 100.0% | +0.0% |
| Tool success | 98.5% | 98.5% | +0.0% |
| Average input tokens | 23.5 | 23.5 | +0.0 |
| Estimated suite cost | $0.000282 | $0.000282 | $+0.000000 |

## Stability

- Top-1 prediction agreement: `100.0%`
- Top-3 ranking agreement: `100.0%`
- Top-1 accuracy range: `93.8%` to `93.8%`

The candidate is reported beside the original baseline on the identical dataset digest. All repetitions and failures remain in the generated JSON report.
