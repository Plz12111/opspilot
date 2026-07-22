from __future__ import annotations

from opspilot.evaluation.models import EvaluationComparison, EvaluationReport


def render_markdown(report: EvaluationReport) -> str:
    metrics = report.metrics
    thresholds = report.thresholds
    rows = [
        ("Top-1 accuracy", metrics.top1_accuracy, thresholds.top1_accuracy, ">="),
        ("Top-3 recall", metrics.top3_recall, thresholds.top3_recall, ">="),
        ("Citation validity", metrics.citation_validity, thresholds.citation_validity, ">="),
        ("Tool success rate", metrics.tool_success_rate, thresholds.tool_success_rate, ">="),
        (
            "Prohibited action rate",
            metrics.prohibited_action_rate,
            thresholds.prohibited_action_rate,
            "<=",
        ),
    ]
    lines = [
        "# OpsPilot Incident Agent Baseline",
        "",
        f"- Suite: `{report.suite_name}`",
        f"- Baseline: `{report.baseline_name}`",
        f"- Cases: `{metrics.case_count}`",
        f"- Dataset SHA-256: `{report.dataset_digest}`",
        f"- Result: `{'PASS' if report.passed else 'FAIL'}`",
        "",
        "## Aggregate metrics",
        "",
        "| Metric | Actual | Threshold | Result |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, actual, threshold, operator in rows:
        passed = actual >= threshold if operator == ">=" else actual <= threshold
        lines.append(
            f"| {name} | {actual:.1%} | {operator} {threshold:.1%} | "
            f"{'PASS' if passed else 'FAIL'} |"
        )
    lines.extend(
        [
            (
                f"| Critical evidence recall | {metrics.critical_evidence_recall:.1%} "
                "| report only | - |"
            ),
            f"| Average steps | {metrics.average_steps:.2f} | report only | - |",
            f"| P95 latency | {metrics.p95_latency_ms} ms | report only | - |",
            "",
            "## Case results",
            "",
            "| Case | Expected | Top prediction | Top-1 | Top-3 | Evidence |",
            "| --- | --- | --- | --- | --- | ---: |",
        ]
    )
    for item in report.cases:
        top = item.predicted_root_causes[0] if item.predicted_root_causes else "undetermined"
        lines.append(
            f"| `{item.case_id}` | `{item.expected_root_cause}` | `{top}` | "
            f"{'PASS' if item.top1_correct else 'FAIL'} | "
            f"{'PASS' if item.top3_recalled else 'FAIL'} | "
            f"{item.critical_evidence_recall:.0%} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "This is a deterministic keyword baseline, not a claim of model intelligence. "
            "Recorded noisy and missing-telemetry cases are kept in the aggregate rather than "
            "removed. Future prompt, model, and retrieval changes must compare against this "
            "same dataset digest.",
            "",
        ]
    )
    return "\n".join(lines)


def render_comparison_markdown(comparison: EvaluationComparison) -> str:
    baseline = comparison.baseline.metrics
    candidate = comparison.candidate.metrics
    lines = [
        "# OpsPilot Baseline Comparison",
        "",
        f"- Dataset SHA-256: `{comparison.dataset_digest}`",
        f"- Cases: `{candidate.case_count}`",
        f"- Repetitions: `{comparison.stability.repetitions}`",
        "",
        "## Baseline vs candidate",
        "",
        "| Metric | Keyword v1 | Source-weighted v2 | Delta |",
        "| --- | ---: | ---: | ---: |",
        (
            f"| Top-1 accuracy | {baseline.top1_accuracy:.1%} | "
            f"{candidate.top1_accuracy:.1%} | {comparison.top1_delta:+.1%} |"
        ),
        (
            f"| Top-3 recall | {baseline.top3_recall:.1%} | "
            f"{candidate.top3_recall:.1%} | {comparison.top3_delta:+.1%} |"
        ),
        (
            f"| Citation validity | {baseline.citation_validity:.1%} | "
            f"{candidate.citation_validity:.1%} | "
            f"{candidate.citation_validity - baseline.citation_validity:+.1%} |"
        ),
        (
            f"| Tool success | {baseline.tool_success_rate:.1%} | "
            f"{candidate.tool_success_rate:.1%} | "
            f"{candidate.tool_success_rate - baseline.tool_success_rate:+.1%} |"
        ),
        (
            f"| Average input tokens | {baseline.average_input_tokens:.1f} | "
            f"{candidate.average_input_tokens:.1f} | {comparison.token_delta:+.1f} |"
        ),
        (
            f"| Estimated suite cost | ${baseline.estimated_suite_cost_usd:.6f} | "
            f"${candidate.estimated_suite_cost_usd:.6f} | "
            f"${comparison.cost_delta_usd:+.6f} |"
        ),
        "",
        "## Stability",
        "",
        f"- Top-1 prediction agreement: `{comparison.stability.top1_agreement:.1%}`",
        f"- Top-3 ranking agreement: `{comparison.stability.top3_agreement:.1%}`",
        (
            "- Top-1 accuracy range: "
            f"`{comparison.stability.top1_accuracy_min:.1%}` to "
            f"`{comparison.stability.top1_accuracy_max:.1%}`"
        ),
        "",
        "The candidate is reported beside the original baseline on the identical dataset "
        "digest. All repetitions and failures remain in the generated JSON report.",
        "",
    ]
    return "\n".join(lines)
