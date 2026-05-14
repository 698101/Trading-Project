#!/usr/bin/env python3
"""Build a concise project scorecard from committed result artifacts."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--output", default="PROJECT_SCORECARD.md", help="Markdown output path.")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def first_row(path: Path) -> dict[str, str]:
    rows = read_csv(path)
    return rows[0] if rows else {}


def find_row(rows: list[dict[str, str]], **matches: str) -> dict[str, str]:
    for row in rows:
        if all(row.get(key) == value for key, value in matches.items()):
            return row
    return {}


def metric_value(rows: list[dict[str, str]], metric: str, column: str) -> str:
    row = find_row(rows, metric=metric)
    return row.get(column, "") if row else ""


def as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def fmt(value: object, digits: int = 3) -> str:
    return f"{as_float(value):.{digits}f}"


def fmt_pct(value: object, digits: int = 2) -> str:
    return f"{as_float(value) * 100.0:.{digits}f}%"


def fmt_bps(value: object, digits: int = 1) -> str:
    return f"{as_float(value):,.{digits}f} bps"


def fmt_int(value: object) -> str:
    return f"{int(as_float(value)):,}"


def markdown_table(rows: list[dict[str, str]], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(row.get(column, "") for column in columns) + " |")
    return lines


def pass_warn_fail_counts(rows: list[dict[str, str]]) -> str:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for row in rows:
        status = row.get("status", "").strip().lower()
        if status in counts:
            counts[status] += 1
    return f"{counts['pass']} pass / {counts['warn']} warn / {counts['fail']} fail"


def validation_row(rows: list[dict[str, str]], variant: str, split: str) -> dict[str, str]:
    for row in rows:
        if (
            row.get("variant") == variant
            and row.get("split") == split
            and row.get("scope") == "combined"
        ):
            return row
    return {}


def build_micro_section(root: Path) -> list[str]:
    results_dir = root / "hft_microstructure" / "Results"
    quality_rows = read_csv(results_dir / "micro_alpha_quality_sharpe_summary.csv")
    validation_rows = read_csv(results_dir / "micro_alpha_validation_summary.csv")
    baseline = find_row(quality_rows, scope="original_mm_baseline")
    quality = find_row(quality_rows, scope="combined")
    prior = find_row(quality_rows, scope="prior_edge_selected")
    symbol_rows = [row for row in quality_rows if row.get("scope") == "selected_quality"]

    combined_rows = [
        {
            "Version": "Original mm baseline",
            "Minute Sharpe": fmt(baseline.get("minute_sharpe")),
            "Daily Sharpe": fmt(baseline.get("daily_sharpe")),
            "Ann. Daily Sharpe": fmt(baseline.get("annualized_daily_sharpe"), 2),
            "Total PnL": fmt_bps(baseline.get("total_pnl_bps")),
            "Worst DD": fmt_bps(baseline.get("worst_drawdown_bps")),
            "Trades": fmt_int(baseline.get("trade_count")),
        },
        {
            "Version": "Prior edge-selected",
            "Minute Sharpe": fmt(prior.get("minute_sharpe")),
            "Daily Sharpe": fmt(prior.get("daily_sharpe")),
            "Ann. Daily Sharpe": fmt(prior.get("annualized_daily_sharpe"), 2),
            "Total PnL": fmt_bps(prior.get("total_pnl_bps")),
            "Worst DD": fmt_bps(prior.get("worst_drawdown_bps")),
            "Trades": fmt_int(prior.get("trade_count")),
        },
        {
            "Version": "Selected quality gate",
            "Minute Sharpe": fmt(quality.get("minute_sharpe")),
            "Daily Sharpe": fmt(quality.get("daily_sharpe")),
            "Ann. Daily Sharpe": fmt(quality.get("annualized_daily_sharpe"), 2),
            "Total PnL": fmt_bps(quality.get("total_pnl_bps")),
            "Worst DD": fmt_bps(quality.get("worst_drawdown_bps")),
            "Trades": fmt_int(quality.get("trade_count")),
        },
    ]
    symbol_table = [
        {
            "Symbol": row.get("symbol", ""),
            "Min Edge": fmt(row.get("min_edge_bps"), 2),
            "100ms Microprice Gate": fmt(row.get("mm_min_entry_microprice_edge_100ms_bps"), 2),
            "100ms Spread Gate": fmt(row.get("mm_min_entry_spread_100ms_bps"), 2),
            "Minute Sharpe": fmt(row.get("minute_sharpe")),
            "Daily Sharpe": fmt(row.get("daily_sharpe")),
            "Total PnL": fmt_bps(row.get("total_pnl_bps")),
            "Trades": fmt_int(row.get("trade_count")),
        }
        for row in symbol_rows
    ]
    minute_delta = as_float(quality.get("minute_sharpe")) - as_float(baseline.get("minute_sharpe"))
    minute_pct = minute_delta / as_float(baseline.get("minute_sharpe"), 1.0)

    lines = [
        "## Micro Alpha",
        "",
        "Source: `hft_microstructure/Results/micro_alpha_quality_sharpe_summary.csv`.",
        "Primary metric: minute Sharpe, because the evidence is intraday quote replay.",
        "",
    ]
    lines.extend(markdown_table(combined_rows, list(combined_rows[0].keys())))
    lines.extend(
        [
            "",
            f"Selected quality gate improvement vs original mm baseline: +{minute_delta:.3f} minute Sharpe ({minute_pct * 100.0:.1f}%).",
            "",
        ]
    )
    lines.extend(markdown_table(symbol_table, list(symbol_table[0].keys())))
    if validation_rows:
        selected_train = validation_row(validation_rows, "selected_quality_gate", "train")
        selected_oos = validation_row(validation_rows, "selected_quality_gate", "oos")
        baseline_oos = validation_row(validation_rows, "original_mm_baseline", "oos")
        validation_table = [
            {
                "Variant": "Original mm baseline",
                "Split": "OOS",
                "Dates": f"{baseline_oos.get('start_date', '')} to {baseline_oos.get('end_date', '')}",
                "Minute Sharpe": fmt(baseline_oos.get("minute_sharpe")),
                "Daily Sharpe": fmt(baseline_oos.get("daily_sharpe")),
                "Total PnL": fmt_bps(baseline_oos.get("total_pnl_bps")),
            },
            {
                "Variant": "Selected quality gate",
                "Split": "Train",
                "Dates": f"{selected_train.get('start_date', '')} to {selected_train.get('end_date', '')}",
                "Minute Sharpe": fmt(selected_train.get("minute_sharpe")),
                "Daily Sharpe": fmt(selected_train.get("daily_sharpe")),
                "Total PnL": fmt_bps(selected_train.get("total_pnl_bps")),
            },
            {
                "Variant": "Selected quality gate",
                "Split": "OOS",
                "Dates": f"{selected_oos.get('start_date', '')} to {selected_oos.get('end_date', '')}",
                "Minute Sharpe": fmt(selected_oos.get("minute_sharpe")),
                "Daily Sharpe": fmt(selected_oos.get("daily_sharpe")),
                "Total PnL": fmt_bps(selected_oos.get("total_pnl_bps")),
            },
        ]
        oos_minute_delta = as_float(selected_oos.get("minute_sharpe")) - as_float(baseline_oos.get("minute_sharpe"))
        lines.extend(["", "Chronological validation sanity check:", ""])
        lines.extend(markdown_table(validation_table, list(validation_table[0].keys())))
        lines.extend(
            [
                "",
                f"Selected quality gate OOS minute Sharpe improvement vs original mm baseline: {oos_minute_delta:+.3f}.",
                "",
            ]
        )
    lines.extend(
        [
            "Current boundary: this is Alpaca IEX top-of-book evidence over 51 SPY/QQQ/IWM open-window sessions, not full depth-of-book or live fills.",
            "",
        ]
    )
    return lines


def build_medium_section(root: Path) -> list[str]:
    results_dir = root / "medium_term_alpha" / "Results"
    selected = first_row(results_dir / "selected_default_metrics.csv")
    comparison = read_csv(results_dir / "benchmark_comparison.csv")
    robustness = read_csv(results_dir / "medium_alpha_robustness_scorecard.csv")

    rows = [
        {
            "Metric": "Annualized Sharpe",
            "Strategy": fmt(selected.get("annualized_sharpe"), 4),
            "SPY": fmt(selected.get("benchmark_annualized_sharpe") or metric_value(comparison, "annualized_sharpe", "SPY"), 4),
        },
        {
            "Metric": "Annualized Return",
            "Strategy": fmt_pct(selected.get("annualized_return")),
            "SPY": fmt_pct(selected.get("benchmark_annualized_return") or metric_value(comparison, "annualized_return", "SPY")),
        },
        {
            "Metric": "Total Return",
            "Strategy": fmt_pct(selected.get("total_return")),
            "SPY": fmt_pct(selected.get("benchmark_total_return") or metric_value(comparison, "total_return", "SPY")),
        },
        {
            "Metric": "Max Drawdown",
            "Strategy": fmt_pct(selected.get("max_drawdown")),
            "SPY": fmt_pct(metric_value(comparison, "max_drawdown", "SPY")),
        },
        {
            "Metric": "Annualized Volatility",
            "Strategy": fmt_pct(selected.get("annualized_volatility")),
            "SPY": fmt_pct(metric_value(comparison, "annualized_volatility", "SPY")),
        },
    ]
    lines = [
        "## Medium Alpha",
        "",
        "Source: `medium_term_alpha/Results/selected_default_metrics.csv` and `benchmark_comparison.csv`.",
        "",
    ]
    lines.extend(markdown_table(rows, ["Metric", "Strategy", "SPY"]))
    lines.extend(
        [
            "",
            f"Robustness scorecard: {pass_warn_fail_counts(robustness)}.",
            "Current boundary: the saved result is not point-in-time/delisting-aware and remains momentum-dominated.",
            "",
        ]
    )
    return lines


def build_scorecard(root: Path) -> str:
    lines = [
        "# Project Scorecard",
        "",
        "This file is generated from committed result artifacts by `scripts/build_project_scorecard.py`.",
        "It is intended as the honest recruiter/interviewer view: strong research portfolio evidence, not production trading proof.",
        "",
        "## Overall Rating",
        "",
    ]
    rating_rows = [
        {
            "Dimension": "Quant research portfolio",
            "Rating": "8/10",
            "Reason": "Two independent systems, real result artifacts, stress tests, walk-forward checks, and honest limitations.",
        },
        {
            "Dimension": "Research evidence",
            "Rating": "6.5-7/10",
            "Reason": "Promising metrics with useful robustness work, but still constrained by data realism.",
        },
        {
            "Dimension": "Live trading readiness",
            "Rating": "3-4/10",
            "Reason": "No live fills, no calibrated HFT queue model, and no point-in-time/delisting-aware medium-alpha universe.",
        },
    ]
    lines.extend(markdown_table(rating_rows, ["Dimension", "Rating", "Reason"]))
    lines.extend([""])
    lines.extend(build_micro_section(root))
    lines.extend(build_medium_section(root))
    lines.extend(
        [
            "## Upgrade Priorities",
            "",
            "1. Extend HFT validation to genuinely new dates, more symbols, and additional intraday windows.",
            "2. Add a calibrated passive-fill and queue-position model using execution or order-book data.",
            "3. Replace the medium-alpha universe with point-in-time, delisting-aware data.",
            "4. Keep raw-data manifests and exact run configs pinned so GitHub evidence is reproducible.",
            "5. Add negative controls for shuffled HFT signals and shuffled medium-alpha ranks.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    output.write_text(build_scorecard(root), encoding="utf-8")
    print(f"scorecard={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
