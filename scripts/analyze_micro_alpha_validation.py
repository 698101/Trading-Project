#!/usr/bin/env python3
"""Build chronological train/OOS diagnostics for saved micro-alpha variants.

This script is reporting-only. It consumes saved daily/interval outputs from the
local backtest runs and writes compact artifacts under hft_microstructure/Results.
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path


SYMBOLS = ["SPY", "QQQ", "IWM"]


@dataclass(frozen=True)
class Variant:
    key: str
    label: str
    daily_paths: dict[str, Path]


def default_variants() -> list[Variant]:
    return [
        Variant(
            key="original_mm_baseline",
            label="Original mm baseline",
            daily_paths={
                "SPY": Path("build/real_quote_symbol_suite/spy/real_quote_backtest_mm_only/daily_results.csv"),
                "QQQ": Path("build/real_quote_symbol_suite/qqq/real_quote_backtest_mm_only/daily_results.csv"),
                "IWM": Path("build/real_quote_symbol_suite/iwm/real_quote_backtest_mm_only/daily_results.csv"),
            },
        ),
        Variant(
            key="prior_edge_selected",
            label="Prior edge-selected",
            daily_paths={
                "SPY": Path("build/sharpe_experiments/spy_mm_edge030/daily_results.csv"),
                "QQQ": Path("build/sharpe_experiments/qqq_mm_edge030/daily_results.csv"),
                "IWM": Path("build/sharpe_experiments/iwm_mm_edge075/daily_results.csv"),
            },
        ),
        Variant(
            key="selected_quality_gate",
            label="Selected quality gate",
            daily_paths={
                "SPY": Path("build/sharpe_quality_full/spy_m025_s100/daily_results.csv"),
                "QQQ": Path("build/sharpe_quality_full/qqq_m025_s100/daily_results.csv"),
                "IWM": Path("build/sharpe_experiments/iwm_mm_edge075/daily_results.csv"),
            },
        ),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--train-fraction", type=float, default=0.60)
    parser.add_argument(
        "--output-prefix",
        default="hft_microstructure/Results/micro_alpha_validation",
        help="Output prefix for CSV and Markdown report.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def resolve(root: Path, path: Path | str) -> Path:
    resolved = Path(path)
    return resolved if resolved.is_absolute() else root / resolved


def sample_sharpe(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    stddev = math.sqrt(variance)
    return 0.0 if stddev == 0.0 else mean / stddev


def max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def safe_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def safe_int(value: object) -> int:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def split_dates(dates: list[str], train_fraction: float) -> tuple[list[str], list[str]]:
    unique_dates = sorted(set(dates))
    if len(unique_dates) < 2:
        raise ValueError("At least two dates are required for train/OOS validation.")
    train_count = math.ceil(len(unique_dates) * train_fraction)
    train_count = max(1, min(len(unique_dates) - 1, train_count))
    return unique_dates[:train_count], unique_dates[train_count:]


def variant_dates(root: Path, variant: Variant) -> list[str]:
    dates: set[str] = set()
    for daily_path in variant.daily_paths.values():
        for row in read_csv(resolve(root, daily_path)):
            date = row.get("date")
            if date:
                dates.add(date)
    return sorted(dates)


def interval_returns(root: Path, prefix: str) -> list[float]:
    rows = read_csv(resolve(root, f"{prefix}_intervals.csv"))
    return [safe_float(row.get("return_bps")) for row in rows]


def daily_rows_for_dates(root: Path, daily_path: Path, dates: set[str]) -> list[dict[str, str]]:
    return [row for row in read_csv(resolve(root, daily_path)) if row.get("date") in dates]


def summarize_symbol(root: Path, daily_path: Path, selected_dates: list[str]) -> dict[str, object]:
    date_set = set(selected_dates)
    rows = daily_rows_for_dates(root, daily_path, date_set)
    daily_pnls = [safe_float(row.get("total_net_return_bps")) for row in rows]
    intervals: list[float] = []
    trades = 0
    for row in rows:
        intervals.extend(interval_returns(root, row.get("prefix", "")))
        trades += safe_int(row.get("completed_trades"))
    daily_sharpe = sample_sharpe(daily_pnls)
    return {
        "sessions": len(daily_pnls),
        "start_date": min(selected_dates) if selected_dates else "",
        "end_date": max(selected_dates) if selected_dates else "",
        "total_pnl_bps": sum(daily_pnls),
        "avg_daily_pnl_bps": (sum(daily_pnls) / len(daily_pnls)) if daily_pnls else 0.0,
        "daily_sharpe": daily_sharpe,
        "annualized_daily_sharpe": daily_sharpe * math.sqrt(252.0),
        "minute_sharpe": sample_sharpe(intervals),
        "worst_drawdown_bps": max_drawdown(intervals),
        "trade_count": trades,
    }


def summarize_combined(root: Path, variant: Variant, selected_dates: list[str]) -> dict[str, object]:
    date_set = set(selected_dates)
    daily_by_date: dict[str, float] = {date: 0.0 for date in selected_dates}
    intervals: list[float] = []
    trades = 0
    for daily_path in variant.daily_paths.values():
        for row in daily_rows_for_dates(root, daily_path, date_set):
            daily_by_date[row["date"]] = daily_by_date.get(row["date"], 0.0) + safe_float(row.get("total_net_return_bps"))
            intervals.extend(interval_returns(root, row.get("prefix", "")))
            trades += safe_int(row.get("completed_trades"))
    daily_pnls = [daily_by_date[date] for date in selected_dates]
    daily_sharpe = sample_sharpe(daily_pnls)
    return {
        "sessions": len(daily_pnls),
        "start_date": min(selected_dates) if selected_dates else "",
        "end_date": max(selected_dates) if selected_dates else "",
        "total_pnl_bps": sum(daily_pnls),
        "avg_daily_pnl_bps": (sum(daily_pnls) / len(daily_pnls)) if daily_pnls else 0.0,
        "daily_sharpe": daily_sharpe,
        "annualized_daily_sharpe": daily_sharpe * math.sqrt(252.0),
        "minute_sharpe": sample_sharpe(intervals),
        "worst_drawdown_bps": max_drawdown(intervals),
        "trade_count": trades,
    }


def format_row(
    variant: Variant,
    split: str,
    scope: str,
    symbol: str,
    metrics: dict[str, object],
) -> dict[str, object]:
    return {
        "variant": variant.key,
        "label": variant.label,
        "split": split,
        "scope": scope,
        "symbol": symbol,
        "sessions": metrics["sessions"],
        "start_date": metrics["start_date"],
        "end_date": metrics["end_date"],
        "total_pnl_bps": f"{safe_float(metrics['total_pnl_bps']):.6f}",
        "avg_daily_pnl_bps": f"{safe_float(metrics['avg_daily_pnl_bps']):.6f}",
        "daily_sharpe": f"{safe_float(metrics['daily_sharpe']):.12f}",
        "annualized_daily_sharpe": f"{safe_float(metrics['annualized_daily_sharpe']):.12f}",
        "minute_sharpe": f"{safe_float(metrics['minute_sharpe']):.12f}",
        "worst_drawdown_bps": f"{safe_float(metrics['worst_drawdown_bps']):.6f}",
        "trade_count": metrics["trade_count"],
    }


def build_rows(root: Path, train_fraction: float) -> list[dict[str, object]]:
    variants = default_variants()
    dates = variant_dates(root, variants[-1])
    train_dates, oos_dates = split_dates(dates, train_fraction)
    split_map = {
        "train": train_dates,
        "oos": oos_dates,
        "all": sorted(set(train_dates + oos_dates)),
    }
    rows: list[dict[str, object]] = []
    for variant in variants:
        for split, selected_dates in split_map.items():
            combined = summarize_combined(root, variant, selected_dates)
            rows.append(format_row(variant, split, "combined", "SPY_QQQ_IWM", combined))
            for symbol in SYMBOLS:
                metrics = summarize_symbol(root, variant.daily_paths[symbol], selected_dates)
                rows.append(format_row(variant, split, "symbol", symbol, metrics))
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def number(row: dict[str, object], key: str) -> float:
    return safe_float(row.get(key))


def report_table(rows: list[dict[str, object]], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def combined_row(rows: list[dict[str, object]], variant: str, split: str) -> dict[str, object]:
    for row in rows:
        if row.get("variant") == variant and row.get("split") == split and row.get("scope") == "combined":
            return row
    return {}


def write_report(path: Path, rows: list[dict[str, object]], train_fraction: float) -> None:
    combined = [row for row in rows if row.get("scope") == "combined"]
    compact: list[dict[str, object]] = []
    for row in combined:
        compact.append(
            {
                "variant": row["label"],
                "split": row["split"],
                "sessions": row["sessions"],
                "dates": f"{row['start_date']} to {row['end_date']}",
                "minute_sharpe": f"{number(row, 'minute_sharpe'):.3f}",
                "daily_sharpe": f"{number(row, 'daily_sharpe'):.3f}",
                "total_pnl_bps": f"{number(row, 'total_pnl_bps'):,.1f}",
                "trades": f"{int(number(row, 'trade_count')):,}",
            }
        )

    train_best = max(
        [row for row in combined if row.get("split") == "train"],
        key=lambda row: number(row, "minute_sharpe"),
    )
    selected_train = combined_row(rows, "selected_quality_gate", "train")
    selected_oos = combined_row(rows, "selected_quality_gate", "oos")
    baseline_oos = combined_row(rows, "original_mm_baseline", "oos")
    oos_minute_delta = number(selected_oos, "minute_sharpe") - number(baseline_oos, "minute_sharpe")
    oos_daily_delta = number(selected_oos, "daily_sharpe") - number(baseline_oos, "daily_sharpe")

    lines = [
        "# Micro Alpha Chronological Validation",
        "",
        "This report splits the saved 51-session SPY/QQQ/IWM evidence chronologically into train and OOS windows.",
        f"The train fraction is {train_fraction:.0%}; the split is a validation sanity check, not a full untouched production-grade holdout.",
        "",
        "## Combined Portfolio Metrics",
        "",
    ]
    lines.extend(
        report_table(
            compact,
            ["variant", "split", "sessions", "dates", "minute_sharpe", "daily_sharpe", "total_pnl_bps", "trades"],
        )
    )
    lines.extend(
        [
            "",
            "## Read",
            "",
            f"- Train-selected best tracked variant by combined minute Sharpe: {train_best.get('label')} ({number(train_best, 'minute_sharpe'):.3f}).",
            f"- Selected quality gate OOS: {number(selected_oos, 'minute_sharpe'):.3f} minute Sharpe and {number(selected_oos, 'daily_sharpe'):.3f} daily Sharpe.",
            f"- OOS improvement vs original mm baseline: {oos_minute_delta:+.3f} minute Sharpe and {oos_daily_delta:+.3f} daily Sharpe.",
            "- This helps address pure full-sample tuning risk, but the next stronger step is a genuinely new date range and additional symbols.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    output_prefix = Path(args.output_prefix)
    if not output_prefix.is_absolute():
        output_prefix = root / output_prefix
    rows = build_rows(root, args.train_fraction)
    csv_path = Path(f"{output_prefix}_summary.csv")
    report_path = Path(f"{output_prefix}_report.md")
    write_csv(csv_path, rows)
    write_report(report_path, rows, args.train_fraction)
    print(f"validation_summary={csv_path}")
    print(f"validation_report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
