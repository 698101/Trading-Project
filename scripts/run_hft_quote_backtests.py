#!/usr/bin/env python3
"""Run HFT simulator over quote files from a manifest and aggregate results."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="build/alpaca_verification/quote_manifest.csv")
    parser.add_argument("--exe", default="hft_microstructure/hft_portfolio")
    parser.add_argument("--output-dir", default="build/alpaca_verification/real_quote_backtest")
    parser.add_argument("--max-sessions", type=int, default=30)
    parser.add_argument("--start-date", default="", help="Optional YYYY-MM-DD lower date bound.")
    parser.add_argument("--end-date", default="", help="Optional YYYY-MM-DD upper date bound.")
    parser.add_argument("--rolling-window", type=int, default=75)
    parser.add_argument("--min-edge-bps", type=float, default=0.20)
    parser.add_argument("--forecast-weight", type=float, default=0.70)
    parser.add_argument("--min-reentry-events", type=int, default=40)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-gross-exposure", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--forecast-mode", default="heuristic")
    parser.add_argument("--portfolio-mode", default="full")
    parser.add_argument("--decision-mode", default="off")
    parser.add_argument("--adverse-selection-bps", type=float, default=0.0)
    parser.add_argument("--signal-latency-us", type=int, default=0)
    parser.add_argument("--mm-min-entry-microprice-edge-100ms-bps", type=float, default=0.0)
    parser.add_argument("--mm-min-entry-spread-100ms-bps", type=float, default=0.0)
    parser.add_argument("--mm-max-entry-side-imbalance-1s", type=float, default=1.0)
    return parser.parse_args()


def parse_date(value: str) -> dt.date | None:
    return dt.datetime.strptime(value, "%Y-%m-%d").date() if value else None


def read_manifest(
    path: Path,
    max_sessions: int,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        rows = []
        for row in csv.DictReader(handle):
            if row["status"] != "ok":
                continue
            row_date = parse_date(row.get("date", ""))
            if start_date is not None and (row_date is None or row_date < start_date):
                continue
            if end_date is not None and (row_date is None or row_date > end_date):
                continue
            rows.append(row)
    return rows[:max_sessions]


def parse_stdout_metrics(text: str) -> dict[str, str]:
    metrics: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.startswith("sleeve="):
            continue
        key, value = line.split("=", 1)
        metrics[key.strip()] = value.strip()
    return metrics


def read_interval_returns(path: Path) -> list[float]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [float(row["return_bps"]) for row in csv.DictReader(handle)]


def read_trade_returns(path: Path) -> list[float]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [float(row["weighted_net_pnl_bps"]) for row in csv.DictReader(handle)]


def sample_sharpe(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    std = math.sqrt(variance)
    return 0.0 if std == 0.0 else mean / std


def max_drawdown_bps(interval_returns: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in interval_returns:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return worst


def run_session(args: argparse.Namespace, row: dict[str, str], output_dir: Path) -> dict[str, object]:
    date = row["date"]
    symbol = row.get("symbol") or Path(row["file_path"]).stem.split("_")[0].upper()
    prefix = output_dir / f"{symbol.lower()}_{date.replace('-', '_')}_{args.portfolio_mode}_{args.forecast_mode}"
    command = [
        str(Path(args.exe)),
        row["file_path"],
        "--rolling-window",
        str(args.rolling_window),
        "--min-edge-bps",
        str(args.min_edge_bps),
        "--forecast-weight",
        str(args.forecast_weight),
        "--min-reentry-events",
        str(args.min_reentry_events),
        "--interval-seconds",
        str(args.interval_seconds),
        "--max-gross-exposure",
        str(args.max_gross_exposure),
        "--seed",
        str(args.seed),
        "--forecast-mode",
        args.forecast_mode,
        "--portfolio-mode",
        args.portfolio_mode,
        "--decision-mode",
        args.decision_mode,
        "--adverse-selection-bps",
        str(args.adverse_selection_bps),
        "--signal-latency-us",
        str(args.signal_latency_us),
        "--mm-min-entry-microprice-edge-100ms-bps",
        str(args.mm_min_entry_microprice_edge_100ms_bps),
        "--mm-min-entry-spread-100ms-bps",
        str(args.mm_min_entry_spread_100ms_bps),
        "--mm-max-entry-side-imbalance-1s",
        str(args.mm_max_entry_side_imbalance_1s),
        "--output-prefix",
        str(prefix),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    metrics = parse_stdout_metrics(completed.stdout)
    print(
        "backtested "
        f"date={date} quotes={metrics.get('processed_quotes', '')} "
        f"trades={metrics.get('completed_trades', '')} "
        f"pnl_bps={metrics.get('total_net_return_bps', '')}",
        flush=True,
    )
    return {
        "date": date,
        "symbol": symbol,
        "file_path": row["file_path"],
        "row_count": row["row_count"],
        "prefix": str(prefix),
        "processed_quotes": metrics.get("processed_quotes", ""),
        "completed_trades": metrics.get("completed_trades", ""),
        "skipped_low_edge": metrics.get("skipped_low_edge", ""),
        "missed_expected_edge_bps": metrics.get("missed_expected_edge_bps", ""),
        "return_intervals": metrics.get("return_intervals", ""),
        "total_net_return_bps": metrics.get("total_net_return_bps", ""),
        "max_drawdown_bps": metrics.get("max_drawdown_bps", ""),
        "minute_return_sharpe": metrics.get("minute_return_sharpe", ""),
        "trade_sharpe_reference": metrics.get("trade_sharpe_reference", ""),
        "latency_expired_signals": metrics.get("latency_expired_signals", ""),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = read_manifest(
        Path(args.manifest),
        args.max_sessions,
        start_date=parse_date(args.start_date),
        end_date=parse_date(args.end_date),
    )
    if not rows:
        raise SystemExit("No ok quote sessions found in manifest.")

    daily_rows = [run_session(args, row, output_dir) for row in rows]
    write_csv(output_dir / "daily_results.csv", daily_rows)

    all_intervals: list[float] = []
    all_trades: list[float] = []
    total_pnl = 0.0
    total_trades = 0
    latency_expired_signals = 0
    for row in daily_rows:
        total_pnl += float(row["total_net_return_bps"])
        total_trades += int(row["completed_trades"])
        latency_expired_signals += int(row.get("latency_expired_signals") or 0)
        prefix = Path(str(row["prefix"]))
        all_intervals.extend(read_interval_returns(Path(f"{prefix}_intervals.csv")))
        all_trades.extend(read_trade_returns(Path(f"{prefix}_trades.csv")))

    summary_rows = [
        {
            "label": f"{args.portfolio_mode}_{args.forecast_mode}",
            "sessions": len(daily_rows),
            "total_pnl_bps": f"{total_pnl:.6f}",
            "avg_daily_return_bps": f"{(total_pnl / len(daily_rows)):.6f}",
            "minute_sharpe": f"{sample_sharpe(all_intervals):.12f}",
            "worst_drawdown_bps": f"{max_drawdown_bps(all_intervals):.6f}",
            "trade_count": total_trades,
            "trade_sharpe_reference": f"{sample_sharpe(all_trades):.12f}",
            "latency_expired_signals": latency_expired_signals,
            "quote_source": "Alpaca historical IEX top-of-book quotes",
        }
    ]
    write_csv(output_dir / "results_summary.csv", summary_rows)
    print(f"daily_results={output_dir / 'daily_results.csv'}")
    print(f"results_summary={output_dir / 'results_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
