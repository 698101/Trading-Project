#!/usr/bin/env python3
"""Summarize fresh-date and transfer-symbol micro-alpha validation runs."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


FRESH_CORE = {
    "SPY": Path("build/fresh_oos_20260513_14/spy_quality/daily_results.csv"),
    "QQQ": Path("build/fresh_oos_20260513_14/qqq_quality/daily_results.csv"),
    "IWM": Path("build/fresh_oos_20260513_14/iwm_quality/daily_results.csv"),
}
TRANSFER = {
    "AAPL": Path("build/transfer_oos_202605/aapl_quality/daily_results.csv"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--output-prefix",
        default="hft_microstructure/Results/micro_alpha_extended_validation",
    )
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def resolve(root: Path, path: Path | str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else root / value


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


def interval_returns(root: Path, prefix: str) -> list[float]:
    return [safe_float(row.get("return_bps")) for row in read_csv(resolve(root, f"{prefix}_intervals.csv"))]


def summarize_daily_paths(
    root: Path,
    scope: str,
    label: str,
    paths: dict[str, Path],
    combine_dates: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    all_daily_by_date: dict[str, float] = {}
    all_intervals: list[float] = []
    all_trades = 0

    for symbol, daily_path in paths.items():
        daily_rows = read_csv(resolve(root, daily_path))
        daily_pnls = [safe_float(row.get("total_net_return_bps")) for row in daily_rows]
        intervals: list[float] = []
        trades = 0
        for row in daily_rows:
            date = row.get("date", "")
            all_daily_by_date[date] = all_daily_by_date.get(date, 0.0) + safe_float(row.get("total_net_return_bps"))
            intervals.extend(interval_returns(root, row.get("prefix", "")))
            trades += safe_int(row.get("completed_trades"))
        all_intervals.extend(intervals)
        all_trades += trades
        rows.append(format_metrics(scope, label, symbol, daily_rows, daily_pnls, intervals, trades, str(daily_path)))

    if combine_dates:
        combined_daily = [all_daily_by_date[date] for date in sorted(all_daily_by_date)]
        rows.insert(
            0,
            format_metrics(
                scope,
                label,
                "_".join(paths.keys()),
                [{"date": date} for date in sorted(all_daily_by_date)],
                combined_daily,
                all_intervals,
                all_trades,
                ";".join(str(path) for path in paths.values()),
            ),
        )
    return rows


def detail_rows(root: Path, scope: str, paths: dict[str, Path]) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for symbol, daily_path in paths.items():
        for row in read_csv(resolve(root, daily_path)):
            output.append(
                {
                    "scope": scope,
                    "symbol": symbol,
                    "date": row.get("date", ""),
                    "total_net_return_bps": row.get("total_net_return_bps", ""),
                    "completed_trades": row.get("completed_trades", ""),
                    "minute_return_sharpe": row.get("minute_return_sharpe", ""),
                    "max_drawdown_bps": row.get("max_drawdown_bps", ""),
                    "source_daily_results": str(daily_path),
                }
            )
    return output


def format_metrics(
    scope: str,
    label: str,
    symbol: str,
    daily_rows: list[dict[str, str]],
    daily_pnls: list[float],
    intervals: list[float],
    trades: int,
    source: str,
) -> dict[str, object]:
    daily_sharpe = sample_sharpe(daily_pnls)
    dates = [row.get("date", "") for row in daily_rows if row.get("date")]
    return {
        "scope": scope,
        "label": label,
        "symbol": symbol,
        "sessions": len(daily_pnls),
        "start_date": min(dates) if dates else "",
        "end_date": max(dates) if dates else "",
        "total_pnl_bps": f"{sum(daily_pnls):.6f}",
        "avg_daily_pnl_bps": f"{(sum(daily_pnls) / len(daily_pnls)):.6f}" if daily_pnls else "0.000000",
        "daily_sharpe": f"{daily_sharpe:.12f}",
        "annualized_daily_sharpe": f"{(daily_sharpe * math.sqrt(252.0)):.12f}",
        "minute_sharpe": f"{sample_sharpe(intervals):.12f}",
        "worst_drawdown_bps": f"{max_drawdown(intervals):.6f}",
        "trade_count": trades,
        "source_daily_results": source,
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def number(row: dict[str, object], key: str) -> float:
    return safe_float(row.get(key))


def table(rows: list[dict[str, object]], columns: list[str]) -> list[str]:
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(column, "")) for column in columns) + " |")
    return lines


def write_report(path: Path, rows: list[dict[str, object]]) -> None:
    report_rows = [
        {
            "scope": row["scope"],
            "symbol": row["symbol"],
            "sessions": row["sessions"],
            "dates": f"{row['start_date']} to {row['end_date']}",
            "minute_sharpe": f"{number(row, 'minute_sharpe'):.3f}",
            "daily_sharpe": f"{number(row, 'daily_sharpe'):.3f}",
            "total_pnl_bps": f"{number(row, 'total_pnl_bps'):,.1f}",
            "trades": f"{int(number(row, 'trade_count')):,}",
        }
        for row in rows
    ]
    lines = [
        "# Micro Alpha Extended Validation",
        "",
        "This report summarizes no-retune validation runs added after the original 51-session evidence set.",
        "Fresh core validation uses 2026-05-13 to 2026-05-14, which is useful but statistically small.",
        "Transfer-symbol validation applies the SPY/QQQ quality-gate parameters to AAPL without symbol-specific retuning.",
        "",
        "## Results",
        "",
    ]
    lines.extend(table(report_rows, ["scope", "symbol", "sessions", "dates", "minute_sharpe", "daily_sharpe", "total_pnl_bps", "trades"]))
    lines.extend(
        [
            "",
            "## Read",
            "",
            "- The fresh SPY/QQQ/IWM cut is post-cutoff evidence, but only two sessions, so daily Sharpe is especially fragile.",
            "- The AAPL transfer test is a no-retune cross-symbol check; it is useful directionally, not broad cross-sectional proof.",
            "- The next stronger pass should extend this to more sessions and more symbols once download time allows.",
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
    rows = []
    rows.extend(summarize_daily_paths(root, "fresh_core_oos", "Fresh post-cutoff core symbols", FRESH_CORE, True))
    rows.extend(summarize_daily_paths(root, "transfer_symbol", "No-retune AAPL transfer", TRANSFER, False))
    details = []
    details.extend(detail_rows(root, "fresh_core_oos", FRESH_CORE))
    details.extend(detail_rows(root, "transfer_symbol", TRANSFER))
    csv_path = Path(f"{output_prefix}_summary.csv")
    detail_path = Path(f"{output_prefix}_daily_results.csv")
    report_path = Path(f"{output_prefix}_report.md")
    write_csv(csv_path, rows)
    write_csv(detail_path, details)
    write_report(report_path, rows)
    print(f"extended_validation_summary={csv_path}")
    print(f"extended_validation_daily_results={detail_path}")
    print(f"extended_validation_report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
