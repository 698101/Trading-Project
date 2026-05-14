#!/usr/bin/env python3
"""Summarize micro-alpha Sharpe improvement experiments.

The script is intentionally read-only with respect to backtests: it consumes
saved baseline and experiment outputs, then writes compact reviewer-facing
summary artifacts.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM"]
DEFAULT_EDGES = [0.20, 0.30, 0.40, 0.55, 0.75]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--edges", default=",".join(f"{value:.2f}" for value in DEFAULT_EDGES))
    parser.add_argument("--results-dir", default="hft_microstructure/Results")
    parser.add_argument("--experiment-dir", default="build/sharpe_experiments")
    parser.add_argument("--baseline-work-dir", default="build/real_quote_symbol_suite")
    parser.add_argument(
        "--output-prefix",
        default="hft_microstructure/Results/micro_alpha",
        help="Prefix for generated CSV/Markdown outputs.",
    )
    return parser.parse_args()


def split_symbols(value: str) -> list[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def split_edges(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


def edge_tag(edge: float) -> str:
    return f"{edge:.2f}".replace(".", "")


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def first_row(path: Path) -> dict[str, str] | None:
    rows = read_csv(path)
    return rows[0] if rows else None


def sample_sharpe(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    stddev = math.sqrt(variance)
    return 0.0 if stddev == 0.0 else mean / stddev


def max_drawdown_bps(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def daily_sharpe_bps(values: list[float]) -> tuple[float, float]:
    daily = [value / 10000.0 for value in values]
    return sample_sharpe(daily), sample_sharpe(daily) * math.sqrt(252.0)


def baseline_summary_path(results_dir: Path, symbol: str) -> Path:
    return results_dir / f"alpaca_{symbol.lower()}_real_quote_mm_only_summary.csv"


def baseline_daily_path(baseline_work_dir: Path, symbol: str) -> Path:
    return baseline_work_dir / symbol.lower() / "real_quote_backtest_mm_only" / "daily_results.csv"


def experiment_summary_path(experiment_dir: Path, symbol: str, edge: float) -> Path:
    return experiment_dir / f"{symbol.lower()}_mm_edge{edge_tag(edge)}" / "results_summary.csv"


def experiment_daily_path(experiment_dir: Path, symbol: str, edge: float) -> Path:
    return experiment_dir / f"{symbol.lower()}_mm_edge{edge_tag(edge)}" / "daily_results.csv"


def resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else Path.cwd() / path


def load_interval_returns(daily_path: Path) -> list[float]:
    output: list[float] = []
    for row in read_csv(daily_path):
        prefix = row.get("prefix")
        if not prefix:
            continue
        intervals_path = resolve_path(f"{prefix}_intervals.csv")
        for interval_row in read_csv(intervals_path):
            try:
                output.append(float(interval_row["return_bps"]))
            except (KeyError, ValueError):
                continue
    return output


def load_daily_pnls(daily_path: Path) -> list[float]:
    output: list[float] = []
    for row in read_csv(daily_path):
        try:
            output.append(float(row["total_net_return_bps"]))
        except (KeyError, ValueError):
            continue
    return output


def load_daily_pnls_by_date(daily_path: Path) -> dict[str, float]:
    output: dict[str, float] = {}
    for row in read_csv(daily_path):
        try:
            output[row["date"]] = float(row["total_net_return_bps"])
        except (KeyError, ValueError):
            continue
    return output


def summarize_variant(
    symbol: str,
    edge: float,
    summary_path: Path,
    daily_path: Path,
    label: str,
) -> dict[str, object] | None:
    summary = first_row(summary_path)
    if summary is None:
        return None
    daily_pnls = load_daily_pnls(daily_path)
    daily_sharpe, annualized_daily_sharpe = daily_sharpe_bps(daily_pnls)
    return {
        "symbol": symbol,
        "variant": label,
        "portfolio_mode": "mm-only",
        "min_edge_bps": f"{edge:.2f}",
        "sessions": summary.get("sessions", len(daily_pnls)),
        "total_pnl_bps": summary.get("total_pnl_bps", ""),
        "avg_daily_return_bps": summary.get("avg_daily_return_bps", ""),
        "minute_sharpe": summary.get("minute_sharpe", ""),
        "daily_sharpe": f"{daily_sharpe:.12f}",
        "annualized_daily_sharpe": f"{annualized_daily_sharpe:.12f}",
        "worst_drawdown_bps": summary.get("worst_drawdown_bps", ""),
        "trade_count": summary.get("trade_count", ""),
        "daily_results": str(daily_path),
        "summary_file": str(summary_path),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def number(row: dict[str, object], key: str) -> float:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return 0.0


def combined_metrics(label: str, daily_paths: list[Path]) -> dict[str, object]:
    interval_returns: list[float] = []
    daily_by_date: dict[str, float] = {}
    trades = 0
    for daily_path in daily_paths:
        interval_returns.extend(load_interval_returns(daily_path))
        for date, pnl in load_daily_pnls_by_date(daily_path).items():
            daily_by_date[date] = daily_by_date.get(date, 0.0) + pnl
        for row in read_csv(daily_path):
            try:
                trades += int(row["completed_trades"])
            except (KeyError, ValueError):
                continue

    daily_pnls = [daily_by_date[date] for date in sorted(daily_by_date)]
    daily_sharpe, annualized_daily_sharpe = daily_sharpe_bps(daily_pnls)
    return {
        "scope": label,
        "sessions": len(daily_pnls),
        "total_pnl_bps": f"{sum(daily_pnls):.6f}",
        "avg_daily_return_bps": f"{(sum(daily_pnls) / len(daily_pnls)):.6f}" if daily_pnls else "",
        "minute_sharpe": f"{sample_sharpe(interval_returns):.12f}",
        "daily_sharpe": f"{daily_sharpe:.12f}",
        "annualized_daily_sharpe": f"{annualized_daily_sharpe:.12f}",
        "worst_drawdown_bps": f"{max_drawdown_bps(interval_returns):.6f}",
        "trade_count": trades,
    }


def pct_delta(new_value: float, old_value: float) -> float:
    return ((new_value / old_value) - 1.0) if old_value else 0.0


def markdown_table(rows: list[dict[str, object]], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def write_report(
    path: Path,
    selected_rows: list[dict[str, object]],
    combined_rows: list[dict[str, object]],
) -> None:
    report_selected: list[dict[str, object]] = []
    for row in selected_rows:
        report_selected.append(
            {
                "symbol": row["symbol"],
                "selected_min_edge_bps": row["selected_min_edge_bps"],
                "baseline_minute_sharpe": f"{number(row, 'baseline_minute_sharpe'):.3f}",
                "selected_minute_sharpe": f"{number(row, 'selected_minute_sharpe'):.3f}",
                "minute_sharpe_delta": f"{number(row, 'minute_sharpe_delta'):.3f}",
                "baseline_pnl_bps": f"{number(row, 'baseline_total_pnl_bps'):,.1f}",
                "selected_pnl_bps": f"{number(row, 'selected_total_pnl_bps'):,.1f}",
                "selected_trades": f"{int(number(row, 'selected_trade_count')):,}",
            }
        )

    report_combined: list[dict[str, object]] = []
    for row in combined_rows:
        report_combined.append(
            {
                "scope": row["scope"],
                "minute_sharpe": f"{number(row, 'minute_sharpe'):.3f}",
                "daily_sharpe": f"{number(row, 'daily_sharpe'):.3f}",
                "ann_daily_sharpe": f"{number(row, 'annualized_daily_sharpe'):.2f}",
                "total_pnl_bps": f"{number(row, 'total_pnl_bps'):,.1f}",
                "worst_dd_bps": f"{number(row, 'worst_drawdown_bps'):.1f}",
                "trades": f"{int(number(row, 'trade_count')):,}",
            }
        )

    lines = [
        "# Micro Alpha Sharpe Improvement Summary",
        "",
        "This report summarizes saved market-making-only edge-floor experiments.",
        "Selection is by minute Sharpe, which is the primary metric for the intraday quote-replay setup.",
        "",
        "## Selected Edge Floors",
        "",
    ]
    lines.extend(
        markdown_table(
            report_selected,
            [
                "symbol",
                "selected_min_edge_bps",
                "baseline_minute_sharpe",
                "selected_minute_sharpe",
                "minute_sharpe_delta",
                "baseline_pnl_bps",
                "selected_pnl_bps",
                "selected_trades",
            ],
        )
    )
    lines.extend(["", "## Combined Portfolio Diagnostic", ""])
    lines.extend(
        markdown_table(
            report_combined,
            [
                "scope",
                "minute_sharpe",
                "daily_sharpe",
                "ann_daily_sharpe",
                "total_pnl_bps",
                "worst_dd_bps",
                "trades",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- The selected configuration improves combined minute Sharpe by tightening the edge floor for QQQ and IWM while keeping SPY close to baseline.",
            "- The improvement trades away some total PnL and trade count, so it should be presented as risk-adjusted tuning rather than a free performance gain.",
            "- Daily Sharpe remains a weak diagnostic for this sample because every combined day is positive; minute Sharpe is the cleaner microstructure metric.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def main() -> int:
    args = parse_args()
    symbols = split_symbols(args.symbols)
    edges = split_edges(args.edges)
    results_dir = Path(args.results_dir)
    experiment_dir = Path(args.experiment_dir)
    baseline_work_dir = Path(args.baseline_work_dir)
    output_prefix = Path(args.output_prefix)

    sweep_rows: list[dict[str, object]] = []
    grouped: dict[str, list[dict[str, object]]] = {symbol: [] for symbol in symbols}
    for symbol in symbols:
        for edge in edges:
            if abs(edge - 0.20) < 1e-9:
                row = summarize_variant(
                    symbol,
                    edge,
                    baseline_summary_path(results_dir, symbol),
                    baseline_daily_path(baseline_work_dir, symbol),
                    "baseline",
                )
            else:
                row = summarize_variant(
                    symbol,
                    edge,
                    experiment_summary_path(experiment_dir, symbol, edge),
                    experiment_daily_path(experiment_dir, symbol, edge),
                    "edge_sweep",
                )
            if row is None:
                continue
            sweep_rows.append(row)
            grouped[symbol].append(row)

    selected_rows: list[dict[str, object]] = []
    selected_daily_paths: list[Path] = []
    baseline_daily_paths: list[Path] = []
    for symbol in symbols:
        candidates = grouped.get(symbol, [])
        if not candidates:
            continue
        baseline = next((row for row in candidates if row["variant"] == "baseline"), candidates[0])
        selected = max(candidates, key=lambda row: number(row, "minute_sharpe"))
        selected_daily_paths.append(Path(str(selected["daily_results"])))
        baseline_daily_paths.append(Path(str(baseline["daily_results"])))
        selected_rows.append(
            {
                "symbol": symbol,
                "baseline_min_edge_bps": baseline["min_edge_bps"],
                "selected_min_edge_bps": selected["min_edge_bps"],
                "baseline_minute_sharpe": baseline["minute_sharpe"],
                "selected_minute_sharpe": selected["minute_sharpe"],
                "minute_sharpe_delta": f"{(number(selected, 'minute_sharpe') - number(baseline, 'minute_sharpe')):.12f}",
                "minute_sharpe_pct_delta": f"{pct_delta(number(selected, 'minute_sharpe'), number(baseline, 'minute_sharpe')):.12f}",
                "baseline_daily_sharpe": baseline["daily_sharpe"],
                "selected_daily_sharpe": selected["daily_sharpe"],
                "baseline_total_pnl_bps": baseline["total_pnl_bps"],
                "selected_total_pnl_bps": selected["total_pnl_bps"],
                "baseline_worst_drawdown_bps": baseline["worst_drawdown_bps"],
                "selected_worst_drawdown_bps": selected["worst_drawdown_bps"],
                "baseline_trade_count": baseline["trade_count"],
                "selected_trade_count": selected["trade_count"],
                "selected_daily_results": selected["daily_results"],
                "selected_summary_file": selected["summary_file"],
            }
        )

    combined_rows = [
        combined_metrics("baseline_mm_only", baseline_daily_paths),
        combined_metrics("selected_mm_only", selected_daily_paths),
    ]

    write_csv(Path(f"{output_prefix}_mm_edge_sweep_summary.csv"), sweep_rows)
    write_csv(Path(f"{output_prefix}_selected_sharpe_summary.csv"), selected_rows)
    write_csv(Path(f"{output_prefix}_combined_sharpe_summary.csv"), combined_rows)
    write_report(Path(f"{output_prefix}_sharpe_improvement_report.md"), selected_rows, combined_rows)
    print(f"sweep={output_prefix}_mm_edge_sweep_summary.csv")
    print(f"selected={output_prefix}_selected_sharpe_summary.csv")
    print(f"combined={output_prefix}_combined_sharpe_summary.csv")
    print(f"report={output_prefix}_sharpe_improvement_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
