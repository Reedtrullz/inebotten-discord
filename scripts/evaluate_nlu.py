#!/usr/bin/env python3
"""Evaluate the NLU contract through production parser entry points."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Sequence, cast


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.nlu_harness import (  # noqa: E402
    aggregate_intent_report,
    build_production_router,
    evaluate_case,
    load_cases,
)


DEFAULT_CORPUS = PROJECT_ROOT / "tests" / "fixtures" / "nlu_contract_v1.jsonl"
DEFAULT_REPORT = PROJECT_ROOT / ".artifacts" / "nlu-contract.json"
REQUIRED_METRICS = (
    "overall_exact_intent_accuracy",
    "labeled_payload_accuracy",
    "parser_error_rate",
    "negative_mutation_false_positive_rate",
    "critical_action_recall",
    "destructive_action_precision",
)


def _unit_interval(value: str) -> float:
    try:
        threshold = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "threshold must be a number between 0 and 1"
        ) from exc
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise argparse.ArgumentTypeError(
            "threshold must be finite and between 0 and 1"
        )
    return threshold


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic production-parser NLU contract."
    )
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--min-overall", type=_unit_interval, default=0.98)
    parser.add_argument("--min-locale", type=_unit_interval, default=0.95)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help=(
            "Write the unchanged report and decision, but always exit "
            "successfully."
        ),
    )
    return parser.parse_args(argv)


def _metric_rate(metrics: dict[str, Any], name: str) -> float:
    return float(cast(dict[str, Any], metrics[name])["rate"])


def _report_passes(
    report: dict[str, object], *, min_overall: float, min_locale: float
) -> bool:
    metrics = cast(dict[str, Any], report["metrics"])
    if any(
        not bool(cast(dict[str, Any], metrics[name])["defined"])
        for name in REQUIRED_METRICS
    ):
        return False
    if _metric_rate(metrics, "parser_error_rate") != 0.0:
        return False
    if _metric_rate(metrics, "negative_mutation_false_positive_rate") != 0.0:
        return False
    for name in (
        "destructive_action_precision",
        "critical_action_recall",
        "labeled_payload_accuracy",
    ):
        if _metric_rate(metrics, name) != 1.0:
            return False
    if _metric_rate(metrics, "overall_exact_intent_accuracy") < min_overall:
        return False

    by_locale = cast(dict[str, dict[str, Any]], report["by_locale"])
    for metric in by_locale.values():
        if int(metric["denominator"]) and (
            not bool(metric["defined"]) or float(metric["rate"]) < min_locale
        ):
            return False

    cases = cast(list[dict[str, Any]], report["cases"])
    return not any(bool(case["forbidden_hit"]) for case in cases)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    cases = load_cases(args.corpus)
    results = tuple(
        evaluate_case(
            case,
            build_production_router(case.fixture),
            guild_id=123,
        )
        for case in cases
    )
    report = aggregate_intent_report(results)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    would_pass = _report_passes(
        report,
        min_overall=args.min_overall,
        min_locale=args.min_locale,
    )
    metrics = cast(dict[str, Any], report["metrics"])
    totals = cast(dict[str, Any], report["totals"])
    overall = _metric_rate(metrics, "overall_exact_intent_accuracy")
    print(
        f"NLU contract: cases={totals['cases']} overall={overall:.4f} "
        f"decision={'would-pass' if would_pass else 'would-fail'}"
    )

    if args.report_only:
        return 0
    return 0 if would_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
