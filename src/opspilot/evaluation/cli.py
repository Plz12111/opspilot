from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import TypeAdapter

from opspilot.evaluation.experiment import BaselineComparisonRunner
from opspilot.evaluation.models import EvaluationCase
from opspilot.evaluation.reporting import render_comparison_markdown, render_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the OpsPilot incident-agent baseline")
    parser.add_argument("--cases", type=Path, default=Path("evals/incidents/cases.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("evals/reports"))
    parser.add_argument("--minimum-cases", type=int, default=80)
    parser.add_argument("--repetitions", type=int, default=3)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    raw_cases = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = TypeAdapter(list[EvaluationCase]).validate_python(raw_cases)
    if len(cases) < args.minimum_cases:
        raise ValueError(f"expected at least {args.minimum_cases} cases, found {len(cases)}")
    comparison = await BaselineComparisonRunner(args.repetitions).evaluate(cases)
    report = comparison.candidate
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "incident-baseline.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    (args.output_dir / "incident-baseline.md").write_text(render_markdown(report), encoding="utf-8")
    (args.output_dir / "incident-comparison.json").write_text(
        comparison.model_dump_json(indent=2), encoding="utf-8"
    )
    (args.output_dir / "incident-comparison.md").write_text(
        render_comparison_markdown(comparison), encoding="utf-8"
    )
    print(
        f"{report.suite_name}: {'PASS' if report.passed else 'FAIL'} | "
        f"cases={report.metrics.case_count} | "
        f"top1={report.metrics.top1_accuracy:.1%} | "
        f"top3={report.metrics.top3_recall:.1%} | "
        f"citations={report.metrics.citation_validity:.1%} | "
        f"delta={comparison.top1_delta:+.1%} | "
        f"stability={comparison.stability.top1_agreement:.1%}"
    )
    return 0 if report.passed else 1


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
